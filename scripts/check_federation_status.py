#!/usr/bin/env python3
"""
Check Federation Status
Queries the PseudoDB to show current federation state
"""
import sqlite3
import sys
import os
from datetime import datetime

# Path to DB
DB_PATH = "./db/sample_data.db"

def main():
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found: {DB_PATH}")
        print("   Start the DB server first: python -m fl_main.pseudodb.pseudo_db")
        sys.exit(1)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    print("=" * 60)
    print("🔍 FEDERATION STATUS")
    print("=" * 60)
    print()
    
    # Current Aggregator
    print("📡 Current Aggregator:")
    print("-" * 60)
    c.execute("SELECT aggregator_id, ip, socket, updated_at FROM current_aggregator WHERE id = 1")
    row = c.fetchone()
    if row:
        agg_id, ip, socket, updated_at = row
        print(f"  ID:      {agg_id}")
        print(f"  Address: {ip}:{socket}")
        print(f"  Updated: {updated_at}")
    else:
        print("  ⚠️  No aggregator registered")
        print("     (First agent to start will become aggregator)")
    print()
    
    # Registered Agents
    print("👥 Registered Agents:")
    print("-" * 60)
    c.execute("SELECT agent_id, ip, socket, last_seen FROM agents ORDER BY last_seen DESC")
    rows = c.fetchall()
    if rows:
        for agent_id, ip, socket, last_seen in rows:
            short_id = agent_id[:12] + "..." if len(agent_id) > 12 else agent_id
            print(f"  {short_id}  {ip}:{socket}  (last seen: {last_seen})")
        print(f"\n  Total: {len(rows)} agents")
    else:
        print("  No agents registered yet")
    print()
    
    # Training Rounds
    print("📊 Training Progress:")
    print("-" * 60)
    c.execute("SELECT MAX(round) FROM cluster_models")
    max_round = c.fetchone()[0]
    if max_round is not None:
        print(f"  Latest round: {max_round}")
        
        # Get recent rounds
        c.execute("""
            SELECT round, COUNT(*) as num_local_models 
            FROM local_models 
            GROUP BY round 
            ORDER BY round DESC 
            LIMIT 5
        """)
        recent = c.fetchall()
        if recent:
            print(f"  Recent activity:")
            for r, count in recent:
                print(f"    Round {r}: {count} local models")
    else:
        print("  No training rounds yet")
    print()
    
    conn.close()
    print("=" * 60)

if __name__ == "__main__":
    main()
