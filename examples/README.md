# Example

`python-hello/` is a tiny Python project set up for specsteward, with one approved-ready spec.

```bash
cd examples/python-hello
claude                      # then: /specsteward:init   (keeps the existing sdd.toml)
```

`init` keeps the example's `sdd.toml` but does not trust a file it did not write. Read
it (one `pytest` step), then in Claude Code:

```text
bash .sdd/bin/sdd trust
bash .sdd/bin/sdd analyze 001
bash .sdd/bin/sdd approve 001
/specsteward:run 001
```
