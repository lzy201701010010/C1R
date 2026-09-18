#nullable enable
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;

public static class C1RRankScoreScanner
{
    private sealed class CellInfo
    {
        public int GlobalIndex;
        public string Barcode = "";
        public string Arm = "";
        public string Sample = "";
        public string Donor = "";
    }

    public static string Run(string matrixPath, string mappingPath, string dataset,
        string membershipPath, string cellMapPath, string outputPath,
        string summaryPath, string expectedSha256)
    {
        matrixPath = Path.GetFullPath(matrixPath);
        outputPath = Path.GetFullPath(outputPath);
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);

        var scoreNames = new List<string>();
        var scoreGenes = new List<HashSet<string>>();
        var scoreIndex = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var line in File.ReadLines(membershipPath).Skip(1))
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            var fields = line.Split('\t');
            if (fields.Length != 2) throw new InvalidDataException("Malformed membership row");
            if (!scoreIndex.TryGetValue(fields[0], out int si))
            {
                si = scoreNames.Count;
                scoreIndex.Add(fields[0], si);
                scoreNames.Add(fields[0]);
                scoreGenes.Add(new HashSet<string>(StringComparer.Ordinal));
            }
            if (!scoreGenes[si].Add(fields[1])) throw new InvalidDataException("Duplicate score membership");
        }
        if (scoreNames.Count == 0) throw new InvalidDataException("No score definitions");

        var sourceRows = new List<(int Row, string Symbol, int GroupSize)>();
        using (var reader = new StreamReader(mappingPath, Encoding.UTF8, true))
        {
            var header = reader.ReadLine()!.Split('\t');
            int d = Array.IndexOf(header, "dataset_identifier");
            int r = Array.IndexOf(header, "source_row_index_1based");
            int c = Array.IndexOf(header, "canonical_hgnc_symbol");
            int g = Array.IndexOf(header, "canonical_collapse_group_size");
            if (d < 0 || r < 0 || c < 0 || g < 0) throw new InvalidDataException("Mapping schema mismatch");
            string? line;
            while ((line = reader.ReadLine()) != null)
            {
                var fields = line.Split('\t');
                if (fields[d] != dataset) continue;
                string symbol = fields[c];
                if (string.IsNullOrEmpty(symbol) || symbol.StartsWith("NA_", StringComparison.Ordinal)) symbol = "";
                sourceRows.Add((int.Parse(fields[r], CultureInfo.InvariantCulture), symbol,
                    int.Parse(fields[g], CultureInfo.InvariantCulture)));
            }
        }
        if (sourceRows.Count == 0) throw new InvalidDataException("No mapping rows for " + dataset);
        int sourceFeatureCount = sourceRows.Max(x => x.Row);
        if (sourceRows.Count != sourceFeatureCount) throw new InvalidDataException("Incomplete mapping rows");
        var canonicalIndex = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var item in sourceRows)
            if (item.Symbol.Length > 0 && !canonicalIndex.ContainsKey(item.Symbol)) canonicalIndex.Add(item.Symbol, canonicalIndex.Count);
        int canonicalCount = canonicalIndex.Count;
        var sourceToCanonical = Enumerable.Repeat(-1, sourceFeatureCount + 1).ToArray();
        var canonicalGroupSize = new int[canonicalCount];
        foreach (var item in sourceRows)
        {
            if (item.Symbol.Length == 0) continue;
            int ci = canonicalIndex[item.Symbol];
            sourceToCanonical[item.Row] = ci;
            canonicalGroupSize[ci] = item.GroupSize;
        }

        var canonicalToScores = new List<int>[canonicalCount];
        var mappedMemberCounts = new int[scoreNames.Count];
        for (int si = 0; si < scoreNames.Count; si++)
        {
            foreach (string gene in scoreGenes[si])
            {
                if (!canonicalIndex.TryGetValue(gene, out int ci)) continue;
                canonicalToScores[ci] ??= new List<int>();
                canonicalToScores[ci].Add(si);
                mappedMemberCounts[si]++;
            }
            if (mappedMemberCounts[si] < 3) throw new InvalidDataException("Fewer than three mapped genes for " + scoreNames[si]);
        }
        var targetCanonical = new List<int>();
        var canonicalToTarget = Enumerable.Repeat(-1, canonicalCount).ToArray();
        for (int ci = 0; ci < canonicalCount; ci++)
        {
            if (canonicalToScores[ci] == null) continue;
            canonicalToTarget[ci] = targetCanonical.Count;
            targetCanonical.Add(ci);
        }

        var cells = new List<CellInfo>();
        foreach (var line in File.ReadLines(cellMapPath).Skip(1))
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            var fields = line.Split('\t');
            if (fields.Length != 5) throw new InvalidDataException("Malformed cell-map row");
            cells.Add(new CellInfo {
                GlobalIndex = int.Parse(fields[0], CultureInfo.InvariantCulture),
                Barcode = fields[1], Arm = fields[2], Sample = fields[3], Donor = fields[4]
            });
        }
        if (cells.Count == 0) throw new InvalidDataException("No selected cells");
        var selectedByGlobal = new Dictionary<int, int>();
        for (int i = 0; i < cells.Count; i++)
            if (!selectedByGlobal.TryAdd(cells[i].GlobalIndex, i)) throw new InvalidDataException("Duplicate selected cell");

        var histograms = new Dictionary<long, int>?[cells.Count];
        var detectedCanonical = new int[cells.Count];
        var targetCounts = new long[checked(cells.Count * targetCanonical.Count)];
        var duplicateAccumulation = new Dictionary<long, long>();

        void AddCanonical(int localCell, int canonical, long value)
        {
            if (value <= 0) return;
            var hist = histograms[localCell] ??= new Dictionary<long, int>();
            hist.TryGetValue(value, out int frequency);
            hist[value] = checked(frequency + 1);
            detectedCanonical[localCell] = checked(detectedCanonical[localCell] + 1);
            int ti = canonicalToTarget[canonical];
            if (ti >= 0) targetCounts[checked(localCell * targetCanonical.Count + ti)] = value;
        }

        const int bufferSize = 16 * 1024 * 1024;
        using var stream = new FileStream(matrixPath, FileMode.Open, FileAccess.Read, FileShare.Read, bufferSize, FileOptions.SequentialScan);
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        long fileLength = stream.Length, bytesRead = 0, records = 0;
        var buffer = new byte[bufferSize];
        var headerBuffer = new List<byte>(256);
        long headerLineCount = 0, declaredRows = 0, declaredColumns = 0, declaredRecords = 0;
        bool inBody = false;
        var fields3 = new long[3];
        int fieldCount = 0, nextProgress = 10;
        bool inToken = false, hasDigit = false, negative = false, lineInvalid = false, lineHasContent = false;
        long tokenValue = 0;

        void ResetLine()
        {
            fieldCount = 0; inToken = false; hasDigit = false; negative = false;
            lineInvalid = false; lineHasContent = false; tokenValue = 0;
        }
        void FinalizeToken()
        {
            if (!inToken) return;
            if (!hasDigit || fieldCount >= 3) lineInvalid = true;
            else { fields3[fieldCount++] = negative ? -tokenValue : tokenValue; }
            inToken = false; hasDigit = false; negative = false; tokenValue = 0;
        }
        void FinalizeBodyLine()
        {
            FinalizeToken();
            if (lineInvalid || fieldCount != 3) throw new InvalidDataException("Malformed Matrix Market body line after record " + records);
            int row = checked((int)fields3[0]);
            int col = checked((int)fields3[1]);
            long value = fields3[2];
            records++;
            if (row < 1 || row > sourceFeatureCount || col < 1 || col > declaredColumns || value < 0)
                throw new InvalidDataException("Out-of-bounds or negative Matrix Market value");
            if (value > 0 && selectedByGlobal.TryGetValue(col, out int localCell))
            {
                int canonical = sourceToCanonical[row];
                if (canonical >= 0)
                {
                    if (canonicalGroupSize[canonical] == 1) AddCanonical(localCell, canonical, value);
                    else
                    {
                        long key = ((long)canonical << 32) | (uint)localCell;
                        duplicateAccumulation.TryGetValue(key, out long prior);
                        duplicateAccumulation[key] = checked(prior + value);
                    }
                }
            }
            ResetLine();
        }
        void FinalizeHeaderLine()
        {
            string line = Encoding.ASCII.GetString(headerBuffer.ToArray()).TrimEnd('\r');
            headerBuffer.Clear(); headerLineCount++;
            if (headerLineCount == 1)
            {
                if (line != "%%MatrixMarket matrix coordinate integer general") throw new InvalidDataException("Unexpected Matrix Market banner");
                return;
            }
            if (line.StartsWith('%')) return;
            var parts = line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length != 3 || !long.TryParse(parts[0], out declaredRows) || !long.TryParse(parts[1], out declaredColumns) || !long.TryParse(parts[2], out declaredRecords))
                throw new InvalidDataException("Malformed Matrix Market dimensions");
            if (declaredRows != sourceFeatureCount) throw new InvalidDataException("Feature count mismatch");
            if (cells.Max(x => x.GlobalIndex) > declaredColumns) throw new InvalidDataException("Selected cell out of bounds");
            inBody = true;
        }

        while (true)
        {
            int count = stream.Read(buffer, 0, buffer.Length);
            if (count == 0) break;
            hash.AppendData(buffer, 0, count); bytesRead += count;
            for (int i = 0; i < count; i++)
            {
                byte b = buffer[i];
                if (!inBody)
                {
                    if (b == (byte)'\n') FinalizeHeaderLine(); else headerBuffer.Add(b);
                    continue;
                }
                if (b == (byte)'\n') { FinalizeBodyLine(); continue; }
                if (b == (byte)'\r') continue;
                if (b == (byte)' ' || b == (byte)'\t') { FinalizeToken(); continue; }
                lineHasContent = true;
                if (b >= (byte)'0' && b <= (byte)'9')
                {
                    if (!inToken) { inToken = true; negative = false; }
                    hasDigit = true;
                    checked { tokenValue = tokenValue * 10 + (b - (byte)'0'); }
                    continue;
                }
                if ((b == (byte)'+' || b == (byte)'-') && !inToken)
                { inToken = true; hasDigit = false; negative = b == (byte)'-'; continue; }
                lineInvalid = true;
            }
            int percent = (int)(bytesRead * 100L / fileLength);
            if (percent >= nextProgress)
            {
                Console.WriteLine($"RANK_SCORE_SCAN_{dataset}_PROGRESS={percent}% records={records}");
                nextProgress += 10;
            }
        }
        if (!inBody) throw new InvalidDataException("Missing Matrix Market dimensions");
        if (lineHasContent || inToken || fieldCount > 0 || lineInvalid) FinalizeBodyLine();
        if (records != declaredRecords) throw new InvalidDataException($"Record count mismatch {records} != {declaredRecords}");
        string observedSha256 = Convert.ToHexString(hash.GetHashAndReset());
        if (!observedSha256.Equals(expectedSha256, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Matrix SHA-256 mismatch");

        foreach (var item in duplicateAccumulation)
        {
            int canonical = (int)(item.Key >> 32);
            int localCell = (int)(item.Key & 0xffffffffL);
            AddCanonical(localCell, canonical, item.Value);
        }

        int scoreCount = scoreNames.Count;
        var scores = new double[checked(cells.Count * scoreCount)];
        for (int cell = 0; cell < cells.Count; cell++)
        {
            int zeros = canonicalCount - detectedCanonical[cell];
            if (zeros < 0) throw new InvalidDataException("Detected canonical count exceeds universe");
            double zeroNorm = (((1.0 + zeros) / 2.0) - 1.0) / (canonicalCount - 1.0);
            for (int si = 0; si < scoreCount; si++) scores[cell * scoreCount + si] = mappedMemberCounts[si] * zeroNorm;
            var rankByCount = new Dictionary<long, double>();
            long less = 0;
            if (histograms[cell] != null)
            {
                foreach (var pair in histograms[cell]!.OrderBy(x => x.Key))
                {
                    double averageRank = zeros + less + (pair.Value + 1.0) / 2.0;
                    rankByCount[pair.Key] = (averageRank - 1.0) / (canonicalCount - 1.0);
                    less += pair.Value;
                }
            }
            for (int ti = 0; ti < targetCanonical.Count; ti++)
            {
                long count = targetCounts[cell * targetCanonical.Count + ti];
                if (count <= 0) continue;
                double delta = rankByCount[count] - zeroNorm;
                int canonical = targetCanonical[ti];
                foreach (int si in canonicalToScores[canonical]) scores[cell * scoreCount + si] += delta;
            }
            for (int si = 0; si < scoreCount; si++) scores[cell * scoreCount + si] /= mappedMemberCounts[si];
        }

        using (var writer = new StreamWriter(outputPath, false, new UTF8Encoding(false), 1 << 20))
        {
            writer.Write("cell_index_1based\tbarcode\tarm\tsample\tdonor");
            foreach (string name in scoreNames) writer.Write('\t' + name);
            writer.WriteLine();
            for (int cell = 0; cell < cells.Count; cell++)
            {
                var info = cells[cell];
                writer.Write(info.GlobalIndex.ToString(CultureInfo.InvariantCulture));
                writer.Write('\t' + info.Barcode); writer.Write('\t' + info.Arm);
                writer.Write('\t' + info.Sample); writer.Write('\t' + info.Donor);
                for (int si = 0; si < scoreCount; si++)
                {
                    writer.Write('\t');
                    writer.Write(scores[cell * scoreCount + si].ToString("R", CultureInfo.InvariantCulture));
                }
                writer.WriteLine();
            }
        }

        var summary = new StringBuilder();
        void Add(string key, object value) => summary.Append(key).Append('\t').Append(value).Append('\n');
        Add("dataset", dataset); Add("matrix_sha256", observedSha256); Add("records", records);
        Add("source_feature_count", sourceFeatureCount); Add("canonical_feature_count", canonicalCount);
        Add("selected_cell_count", cells.Count); Add("target_canonical_gene_count", targetCanonical.Count);
        Add("score_count", scoreCount); Add("duplicate_canonical_cell_accumulations", duplicateAccumulation.Count);
        Add("status", "PASS_EXACT_SM02_FLOAT64");
        File.WriteAllText(summaryPath, summary.ToString(), new UTF8Encoding(false));
        return $"RANK_SCORE_STATUS=PASS;DATASET={dataset};CELLS={cells.Count};SCORES={scoreCount};SHA256={observedSha256}";
    }
}
