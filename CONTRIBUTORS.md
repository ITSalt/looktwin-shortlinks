# Contributors

- **glitchfox** (AI agent, getpostingboard.dev): `shorty.py` and `test_shorty.py`, including the printable-ASCII URL rule against header injection. Board task #966, posts 6c958cf0 and bb0541be, 30.10.2026. Accepted by the studio unchanged (shorty.py sha256 b617048c73a0…, test_shorty.py 76a487c30482…). v3: the `;params` leak and origin-only referrers (posts 78403dc1 and ecfbc3ae; shorty.py b0fb48ea878a…, test_shorty.py 8d6ecb634068…).
- **rosenrot** (AI agent, getpostingboard.dev): review of v1 that found that deeply nested JSON dropped the connection (RecursionError, now 400) and the missing request timeout (post 6094d338), 30.10.2026.
- **LookTwin studio** (ITSalt): the task, acceptance checks, README.
