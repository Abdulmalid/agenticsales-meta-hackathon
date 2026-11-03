"""Several threads searching one corpus at once (a post planned for several platforms) must all get complete answers."""
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from agentic_sales.corpus.store import CorpusStore


class ParallelSearch(unittest.TestCase):
    def test_many_threads_searching_one_store_never_get_a_broken_row(self):
        root = Path(tempfile.mkdtemp())
        raw = root / "raw"
        raw.mkdir()
        lines = [json.dumps({"text": f"record {i} about phones and shoes"}) for i in range(400)]
        data = "\n".join(lines).encode()
        (raw / "f.jsonl").write_bytes(data)
        con = sqlite3.connect(root / "i.db")
        con.executescript("""CREATE TABLE docs(id INTEGER PRIMARY KEY, domain TEXT, family TEXT, layer TEXT, register TEXT, region TEXT, channel TEXT, situation TEXT,
            platform TEXT, surface TEXT, objective TEXT, industries TEXT, report_id TEXT, title TEXT, src_file TEXT NOT NULL, offset INTEGER, length INTEGER, hash TEXT);
            CREATE VIRTUAL TABLE fts USING fts5(title, body, tags);""")
        pos = 0
        for i, line in enumerate(lines, start=1):
            n = len(line.encode())
            con.execute("INSERT INTO docs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (i, "smm", "meta", "x", "", "", "", "", "meta", "", "conversion", "||", "", f"t{i}", "f.jsonl", pos, n, ""))
            con.execute("INSERT INTO fts(rowid, title, body, tags) VALUES(?,?,?,?)", (i, f"phones {i}", "phones shoes", ""))
            pos += n + 1
        con.commit()
        con.close()
        store = CorpusStore(root / "i.db", raw)
        problems = []

        def work():
            try:
                for _ in range(60):
                    hits = store.search("smm", "phones", limit=5)
                    assert len(hits) == 5 and all(h.title.startswith("t") and isinstance(h.record, dict) for h in hits), len(hits)
            except Exception as e:                                           # noqa: BLE001
                problems.append(repr(e))

        threads = [threading.Thread(target=work) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
