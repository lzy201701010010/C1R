#nullable enable
using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

public static class MatrixScannerEntry
{
    public static string Run(string inputPath, string outputPath)
    {
        inputPath = Path.GetFullPath(inputPath);
        outputPath = Path.GetFullPath(outputPath);
        var result = ScanMatrix(inputPath);
        var json = JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(outputPath, json + Environment.NewLine, new UTF8Encoding(false));
        return $"MATRIX_SCAN_STATUS={result.IntegrityStatus};MATRIX_SCAN_RECORDS={result.ObservedCompleteCoordinateRecords};MATRIX_SCAN_SHA256={result.Sha256}";
    }

private static MatrixScanResult ScanMatrix(string path)
{
    const string expectedBanner = "%%MatrixMarket matrix coordinate integer general";
    const int bufferSize = 16 * 1024 * 1024;
    using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, bufferSize, FileOptions.SequentialScan);
    using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
    var fileLength = stream.Length;
    var buffer = new byte[bufferSize];
    var headerBuffer = new List<byte>(256);
    var headerLineCount = 0L;
    var inBody = false;
    var banner = "";
    long declaredRows = 0, declaredColumns = 0, declaredRecords = 0;

    long records = 0, malformedRows = 0;
    long? minRow = null, maxRow = null, minCol = null, maxCol = null, minValue = null, maxValue = null;
    long[]? firstCoordinate = null, lastCoordinate = null;
    var fields = new long[3];
    var fieldCount = 0;
    var inToken = false;
    var hasDigit = false;
    var negative = false;
    long tokenValue = 0;
    var lineInvalid = false;
    var lineHasContent = false;
    var lastByteWasLf = false;
    long bytesRead = 0;
    var nextProgress = 10;

    void ResetBodyLine()
    {
        fieldCount = 0;
        inToken = false;
        hasDigit = false;
        negative = false;
        tokenValue = 0;
        lineInvalid = false;
        lineHasContent = false;
    }

    void FinalizeToken()
    {
        if (!inToken)
            return;
        if (!hasDigit || fieldCount >= 3)
        {
            lineInvalid = true;
        }
        else
        {
            fields[fieldCount] = negative ? -tokenValue : tokenValue;
            fieldCount++;
        }
        inToken = false;
        hasDigit = false;
        negative = false;
        tokenValue = 0;
    }

    void FinalizeBodyLine()
    {
        FinalizeToken();
        if (!lineHasContent && fieldCount == 0 && !lineInvalid)
        {
            lineInvalid = true;
        }
        if (lineInvalid || fieldCount != 3)
        {
            malformedRows++;
            ResetBodyLine();
            return;
        }
        var row = fields[0];
        var col = fields[1];
        var value = fields[2];
        records++;
        firstCoordinate ??= new[] { row, col, value };
        lastCoordinate = new[] { row, col, value };
        minRow = minRow is null ? row : Math.Min(minRow.Value, row);
        maxRow = maxRow is null ? row : Math.Max(maxRow.Value, row);
        minCol = minCol is null ? col : Math.Min(minCol.Value, col);
        maxCol = maxCol is null ? col : Math.Max(maxCol.Value, col);
        minValue = minValue is null ? value : Math.Min(minValue.Value, value);
        maxValue = maxValue is null ? value : Math.Max(maxValue.Value, value);
        ResetBodyLine();
    }

    void FinalizeHeaderLine()
    {
        var line = Encoding.ASCII.GetString(headerBuffer.ToArray()).TrimEnd('\r');
        headerBuffer.Clear();
        headerLineCount++;
        if (headerLineCount == 1)
        {
            banner = line;
            if (!string.Equals(banner, expectedBanner, StringComparison.Ordinal))
                throw new InvalidDataException($"Unexpected Matrix Market banner: {banner}");
            return;
        }
        if (line.StartsWith('%'))
            return;
        var parts = line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length != 3 ||
            !long.TryParse(parts[0], out declaredRows) ||
            !long.TryParse(parts[1], out declaredColumns) ||
            !long.TryParse(parts[2], out declaredRecords))
        {
            throw new InvalidDataException($"Malformed Matrix Market dimension line: {line}");
        }
        inBody = true;
    }

    while (true)
    {
        var count = stream.Read(buffer, 0, buffer.Length);
        if (count == 0)
            break;
        hash.AppendData(buffer, 0, count);
        bytesRead += count;
        for (var i = 0; i < count; i++)
        {
            var value = buffer[i];
            lastByteWasLf = value == (byte)'\n';
            if (!inBody)
            {
                if (value == (byte)'\n')
                    FinalizeHeaderLine();
                else
                    headerBuffer.Add(value);
                continue;
            }

            if (value == (byte)'\n')
            {
                FinalizeBodyLine();
                continue;
            }
            if (value == (byte)'\r')
                continue;
            if (value == (byte)' ' || value == (byte)'\t')
            {
                FinalizeToken();
                continue;
            }
            lineHasContent = true;
            if (value >= (byte)'0' && value <= (byte)'9')
            {
                if (!inToken)
                {
                    inToken = true;
                    negative = false;
                }
                hasDigit = true;
                try
                {
                    checked { tokenValue = tokenValue * 10 + (value - (byte)'0'); }
                }
                catch (OverflowException)
                {
                    lineInvalid = true;
                }
                continue;
            }
            if ((value == (byte)'+' || value == (byte)'-') && !inToken)
            {
                inToken = true;
                hasDigit = false;
                negative = value == (byte)'-';
                continue;
            }
            lineInvalid = true;
        }

        var percent = (int)(bytesRead * 100L / fileLength);
        if (percent >= nextProgress)
        {
            Console.WriteLine($"MATRIX_SCAN_PROGRESS={percent}% records={records}");
            nextProgress += 10;
        }
    }

    if (!inBody)
    {
        if (headerBuffer.Count > 0)
            FinalizeHeaderLine();
        if (!inBody)
            throw new InvalidDataException("Matrix Market dimension line not found");
    }
    else if (lineHasContent || inToken || fieldCount > 0 || lineInvalid)
    {
        FinalizeBodyLine();
    }

    var rowBoundsValid = minRow is not null && minRow >= 1 && maxRow <= declaredRows;
    var columnBoundsValid = minCol is not null && minCol >= 1 && maxCol <= declaredColumns;
    var integerValuesValid = minValue is not null && minValue >= 0;
    var pass = banner == expectedBanner &&
               declaredRows == 20_028 &&
               declaredColumns == 123_006 &&
               declaredRecords == 174_423_911 &&
               records == declaredRecords &&
               malformedRows == 0 &&
               rowBoundsValid &&
               columnBoundsValid &&
               integerValuesValid;

    return new MatrixScanResult
    {
        Banner = banner,
        DeclaredRows = declaredRows,
        DeclaredColumns = declaredColumns,
        DeclaredCoordinateRecords = declaredRecords,
        ObservedCompleteCoordinateRecords = records,
        CoordinateDeficit = declaredRecords - records,
        MalformedCoordinateRows = malformedRows,
        HeaderLineCount = headerLineCount,
        TotalLineCount = headerLineCount + records + malformedRows,
        EofHadTerminalNewline = lastByteWasLf,
        RowBoundsValid = rowBoundsValid,
        ColumnBoundsValid = columnBoundsValid,
        IntegerValuesValid = integerValuesValid,
        MinRow = minRow,
        MaxRow = maxRow,
        MinCol = minCol,
        MaxCol = maxCol,
        MinValue = minValue,
        MaxValue = maxValue,
        FirstCoordinate = firstCoordinate,
        LastCoordinate = lastCoordinate,
        Sha256 = Convert.ToHexString(hash.GetHashAndReset()),
        IntegrityStatus = pass ? "PASS" : "FAIL"
    };
}
}

public sealed class MatrixScanResult
{
    public string Banner { get; set; } = "";
    public long DeclaredRows { get; set; }
    public long DeclaredColumns { get; set; }
    public long DeclaredCoordinateRecords { get; set; }
    public long ObservedCompleteCoordinateRecords { get; set; }
    public long CoordinateDeficit { get; set; }
    public long MalformedCoordinateRows { get; set; }
    public long HeaderLineCount { get; set; }
    public long TotalLineCount { get; set; }
    public bool EofHadTerminalNewline { get; set; }
    public bool RowBoundsValid { get; set; }
    public bool ColumnBoundsValid { get; set; }
    public bool IntegerValuesValid { get; set; }
    public long? MinRow { get; set; }
    public long? MaxRow { get; set; }
    public long? MinCol { get; set; }
    public long? MaxCol { get; set; }
    public long? MinValue { get; set; }
    public long? MaxValue { get; set; }
    public long[]? FirstCoordinate { get; set; }
    public long[]? LastCoordinate { get; set; }
    public string Sha256 { get; set; } = "";
    public string IntegrityStatus { get; set; } = "FAIL";
}
