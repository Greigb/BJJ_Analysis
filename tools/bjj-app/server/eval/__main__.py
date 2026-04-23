"""`python -m server.eval` → delegate to cli.main."""
from server.eval.cli import main

raise SystemExit(main())
