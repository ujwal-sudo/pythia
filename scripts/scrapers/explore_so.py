"""Explore the Stack Exchange HF dataset structure."""

from __future__ import annotations

from datasets import load_dataset

def main():
    ds = load_dataset("raj2708/stackexchange-all", split="train", streaming=True)

    communities = {}
    so_count = 0
    record_types = set()
    total = 0

    for i, rec in enumerate(ds):
        total += 1
        meta = rec.get("metadata", {})
        comm = meta.get("community", "")
        record_types.add(rec.get("type", ""))

        communities[comm] = communities.get(comm, 0) + 1

        if "stackoverflow" in comm.lower():
            so_count += 1

        if total % 50000 == 0:
            print(f"Scanned {total} records, {len(communities)} communities, SO: {so_count}")

        if total >= 500000:
            print(f"Reached 500k limit. Total: {total}, SO: {so_count}, Communities: {len(communities)}")
            break

    print(f"\nTotal: {total}")
    print(f"Stack Overflow records (stackoverflow in community): {so_count}")
    print(f"Record types: {record_types}")
    print(f"\nCommunity counts (top 40):")
    for k, v in sorted(communities.items(), key=lambda x: -x[1])[:40]:
        marker = " <-- SO" if "stackoverflow" in k.lower() else ""
        print(f"  {k}: {v}{marker}")


if __name__ == "__main__":
    main()