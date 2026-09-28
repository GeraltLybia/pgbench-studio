\set bid 1
BEGIN ISOLATION LEVEL REPEATABLE READ;
UPDATE pgbench_branches SET bbalance = bbalance + 1 WHERE bid = :bid;
END;
