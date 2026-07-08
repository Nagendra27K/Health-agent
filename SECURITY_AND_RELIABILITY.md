# Security and Reliability Review

## Controls implemented
- Only local `.xlsx` input is accepted.
- 25 MB input size limit and 200,000-row processing limit reduce resource-exhaustion risk.
- Workbook macros, scripts, links, and formulas are never executed.
- Required schema validation prevents misleading output from unrelated spreadsheets.
- Dates and numeric variance values use defensive parsing.
- Missing values remain Unknown; they are never silently converted to Green.
- Output filenames are sanitized to prevent path traversal.
- JSON is strict (`NaN` and Infinity are rejected).
- Outputs use atomic writes to avoid half-written/corrupt files.
- Each file is isolated: one bad workbook does not crash processing of the remaining files.
- Unexpected errors are caught without exposing internal stack traces by default.
- No API key is required and no project data is sent over the network.
- The agent never executes shell commands from workbook content.

## Reliability behavior
The agent cannot literally be guaranteed to “never break” under every possible hardware, operating-system, corrupted-file, or dependency failure. The design instead fails safely, returns a non-zero exit code, preserves other valid outputs, and gives controlled error messages.

## Test coverage included
- Valid processing of both supplied project plans
- Missing-file rejection
- Unsupported-file rejection
- Invalid-date rejection
- Status normalization
- Variance parsing
- Output-name sanitization

## Production recommendations
Pin dependency versions with hashes, run in a non-root container, add malware scanning before upload, store logs without client-sensitive data, encrypt storage, add role-based access, and run scheduled backups/monitoring.
