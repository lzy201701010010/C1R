# Reproducibility status

| Check | Current state |
| --- | --- |
| Historical source snapshot | 16 scripts staged; original file hashes tracked in companion `C1R_CODE_STRUCTURE.tsv` |
| Python parsing | Passed in the predecessor preparation audit |
| R figure-script parsing | Passed for the two figure scripts with R 4.4.2 |
| C# compilation | Not verified |
| Combined environment solve | Not verified |
| Portable execution | Not verified; historical absolute paths and frozen input contracts remain |
| Independent end-to-end reproduction | Not verified; exact raw objects and donor-level derivatives are not packaged |
| Frozen reported outputs | Eight machine-readable result tables staged with source-identical hashes |

The frozen science and source scripts were not edited to force portability. A separately audited port and execution would be needed before claiming standalone reproducibility. This package supports code inspection and inspection of the reported tables.
