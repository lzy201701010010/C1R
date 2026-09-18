#nullable enable
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;

public static class C1RMatrixQcScanner
{
    public static string Run(string inputPath, string mitochondrialRowPath, string outputPrefix)
    {
        inputPath = Path.GetFullPath(inputPath);
        outputPrefix = Path.GetFullPath(outputPrefix);
        Directory.CreateDirectory(Path.GetDirectoryName(outputPrefix)!);

        var mitochondrialRows = new HashSet<long>();
        foreach (var line in File.ReadLines(mitochondrialRowPath))
        {
            if (!string.IsNullOrWhiteSpace(line))
                mitochondrialRows.Add(long.Parse(line, CultureInfo.InvariantCulture));
        }

        const int bufferSize = 16 * 1024 * 1024;
        using var stream = new FileStream(inputPath, FileMode.Open, FileAccess.Read, FileShare.Read, bufferSize, FileOptions.SequentialScan);
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var fileLength = stream.Length;
        var buffer = new byte[bufferSize];
        var headerBuffer = new List<byte>(256);
        long headerLineCount = 0;
        bool inBody = false;
        string banner = "";
        long declaredRows = 0, declaredColumns = 0, declaredRecords = 0;
        long[]? totalCounts = null;
        int[]? detectedGenes = null;
        long[]? mitochondrialCounts = null;

        long records = 0, malformedRows = 0, explicitZeros = 0, duplicateCoordinates = 0;
        long? minRow = null, maxRow = null, minCol = null, maxCol = null, minValue = null, maxValue = null;
        long previousRow = -1, previousCol = -1;
        bool rowMajorNondecreasing = true, columnMajorNondecreasing = true;
        var fields = new long[3];
        int fieldCount = 0;
        bool inToken = false, hasDigit = false, negative = false, lineInvalid = false, lineHasContent = false;
        long tokenValue = 0, bytesRead = 0;
        int nextProgress = 10;

        void ResetBodyLine()
        {
            fieldCount = 0; inToken = false; hasDigit = false; negative = false;
            tokenValue = 0; lineInvalid = false; lineHasContent = false;
        }

        void FinalizeToken()
        {
            if (!inToken) return;
            if (!hasDigit || fieldCount >= 3) lineInvalid = true;
            else { fields[fieldCount] = negative ? -tokenValue : tokenValue; fieldCount++; }
            inToken = false; hasDigit = false; negative = false; tokenValue = 0;
        }

        void FinalizeBodyLine()
        {
            FinalizeToken();
            if (!lineHasContent && fieldCount == 0 && !lineInvalid) lineInvalid = true;
            if (lineInvalid || fieldCount != 3) { malformedRows++; ResetBodyLine(); return; }
            long row = fields[0], col = fields[1], value = fields[2];
            records++;
            minRow = minRow is null ? row : Math.Min(minRow.Value, row);
            maxRow = maxRow is null ? row : Math.Max(maxRow.Value, row);
            minCol = minCol is null ? col : Math.Min(minCol.Value, col);
            maxCol = maxCol is null ? col : Math.Max(maxCol.Value, col);
            minValue = minValue is null ? value : Math.Min(minValue.Value, value);
            maxValue = maxValue is null ? value : Math.Max(maxValue.Value, value);
            if (previousRow >= 0)
            {
                if (row < previousRow || (row == previousRow && col < previousCol)) rowMajorNondecreasing = false;
                if (col < previousCol || (col == previousCol && row < previousRow)) columnMajorNondecreasing = false;
                if (row == previousRow && col == previousCol) duplicateCoordinates++;
            }
            previousRow = row; previousCol = col;
            if (row >= 1 && row <= declaredRows && col >= 1 && col <= declaredColumns && value >= 0)
            {
                int cell = checked((int)(col - 1));
                if (value == 0) explicitZeros++;
                else
                {
                    totalCounts![cell] = checked(totalCounts[cell] + value);
                    detectedGenes![cell] = checked(detectedGenes[cell] + 1);
                    if (mitochondrialRows.Contains(row)) mitochondrialCounts![cell] = checked(mitochondrialCounts[cell] + value);
                }
            }
            ResetBodyLine();
        }

        void FinalizeHeaderLine()
        {
            string line = Encoding.ASCII.GetString(headerBuffer.ToArray()).TrimEnd('\r');
            headerBuffer.Clear(); headerLineCount++;
            if (headerLineCount == 1)
            {
                banner = line;
                if (banner != "%%MatrixMarket matrix coordinate integer general") throw new InvalidDataException("Unexpected Matrix Market banner: " + banner);
                return;
            }
            if (line.StartsWith('%')) return;
            string[] parts = line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length != 3 || !long.TryParse(parts[0], out declaredRows) || !long.TryParse(parts[1], out declaredColumns) || !long.TryParse(parts[2], out declaredRecords))
                throw new InvalidDataException("Malformed Matrix Market dimension line: " + line);
            if (declaredRows <= 0 || declaredColumns <= 0 || declaredColumns > int.MaxValue || declaredRecords < 0)
                throw new InvalidDataException("Invalid Matrix Market dimensions");
            totalCounts = new long[(int)declaredColumns];
            detectedGenes = new int[(int)declaredColumns];
            mitochondrialCounts = new long[(int)declaredColumns];
            inBody = true;
        }

        while (true)
        {
            int count = stream.Read(buffer, 0, buffer.Length);
            if (count == 0) break;
            hash.AppendData(buffer, 0, count); bytesRead += count;
            for (int i = 0; i < count; i++)
            {
                byte value = buffer[i];
                if (!inBody)
                {
                    if (value == (byte)'\n') FinalizeHeaderLine(); else headerBuffer.Add(value);
                    continue;
                }
                if (value == (byte)'\n') { FinalizeBodyLine(); continue; }
                if (value == (byte)'\r') continue;
                if (value == (byte)' ' || value == (byte)'\t') { FinalizeToken(); continue; }
                lineHasContent = true;
                if (value >= (byte)'0' && value <= (byte)'9')
                {
                    if (!inToken) { inToken = true; negative = false; }
                    hasDigit = true;
                    try { checked { tokenValue = tokenValue * 10 + (value - (byte)'0'); } } catch (OverflowException) { lineInvalid = true; }
                    continue;
                }
                if ((value == (byte)'+' || value == (byte)'-') && !inToken)
                { inToken = true; hasDigit = false; negative = value == (byte)'-'; continue; }
                lineInvalid = true;
            }
            int percent = (int)(bytesRead * 100L / fileLength);
            if (percent >= nextProgress)
            {
                Console.WriteLine($"QC_MATRIX_SCAN_PROGRESS={percent}% records={records}");
                nextProgress += 10;
            }
        }
        if (!inBody)
        {
            if (headerBuffer.Count > 0) FinalizeHeaderLine();
            if (!inBody) throw new InvalidDataException("Matrix Market dimension line not found");
        }
        else if (lineHasContent || inToken || fieldCount > 0 || lineInvalid) FinalizeBodyLine();

        bool rowBoundsValid = minRow is not null && minRow >= 1 && maxRow <= declaredRows;
        bool columnBoundsValid = minCol is not null && minCol >= 1 && maxCol <= declaredColumns;
        bool valuesValid = minValue is not null && minValue >= 0;
        bool orderProvesUniqueness = rowMajorNondecreasing || columnMajorNondecreasing;
        bool pass = records == declaredRecords && malformedRows == 0 && rowBoundsValid && columnBoundsValid && valuesValid && duplicateCoordinates == 0 && orderProvesUniqueness;
        string digest = Convert.ToHexString(hash.GetHashAndReset());

        using (var writer = new BinaryWriter(File.Create(outputPrefix + ".total_counts.i64"))) foreach (long value in totalCounts!) writer.Write(value);
        using (var writer = new BinaryWriter(File.Create(outputPrefix + ".detected_genes.i32"))) foreach (int value in detectedGenes!) writer.Write(value);
        using (var writer = new BinaryWriter(File.Create(outputPrefix + ".mitochondrial_counts.i64"))) foreach (long value in mitochondrialCounts!) writer.Write(value);

        var summary = new StringBuilder();
        void Add(string key, object? value) => summary.Append(key).Append('\t').Append(value?.ToString() ?? "NA").Append('\n');
        Add("banner", banner); Add("declared_rows", declaredRows); Add("declared_columns", declaredColumns); Add("declared_records", declaredRecords);
        Add("observed_records", records); Add("malformed_rows", malformedRows); Add("min_row", minRow); Add("max_row", maxRow);
        Add("min_col", minCol); Add("max_col", maxCol); Add("min_value", minValue); Add("max_value", maxValue);
        Add("explicit_zero_entries", explicitZeros); Add("duplicate_coordinates", duplicateCoordinates);
        Add("row_major_nondecreasing", rowMajorNondecreasing); Add("column_major_nondecreasing", columnMajorNondecreasing);
        Add("coordinate_uniqueness_proven", orderProvesUniqueness); Add("sha256", digest); Add("integrity_status", pass ? "PASS" : "FAIL");
        File.WriteAllText(outputPrefix + ".summary.tsv", summary.ToString(), new UTF8Encoding(false));
        if (!pass) throw new InvalidDataException("Matrix QC scan failed; see " + outputPrefix + ".summary.tsv");
        return $"QC_MATRIX_SCAN_STATUS=PASS;RECORDS={records};SHA256={digest}";
    }
}
