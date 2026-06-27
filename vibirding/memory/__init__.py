"""Memory: the agent's append-only observation log.

A single JSONL file where every line is one Observation; history is never
rewritten or deleted (architecture principle 4). See log.py for the Log class
(append / query). The append_log tool (tools/log_write.py) is the only writer.
"""
