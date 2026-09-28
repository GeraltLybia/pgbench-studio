\set r random(1, 100)
\if :r > 97
SELECT 1 / 0;
\else
SELECT 1;
\endif
