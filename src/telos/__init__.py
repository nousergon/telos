"""telos — a deterministic personal tax engine.

Greek τέλος: completion, purpose — and the ancient word for a tax or duty.

Load-bearing invariants (see README):
1. No LLM in the arithmetic path — ever.
2. Constants are data, sourced from primary documents (see ``telos.params``).
3. Coverage guard — unrecognized inputs fail loud (see ``telos.engine.guard``).
4. Every output line is traceable to inputs and citations (see ``telos.engine.trace``).
5. Local-first: personal tax data never enters version control.
"""

__version__ = "0.1.0"
