-- Add columns that were missing when paper_trades was first created
alter table paper_trades
    add column if not exists stop_loss_pct numeric,
    add column if not exists target_pct numeric,
    add column if not exists stop_price numeric,
    add column if not exists target_price numeric;

-- Add columns that pipeline/run.py actually inserts into conviction_screen_runs
alter table conviction_screen_runs
    add column if not exists quarter text,
    add column if not exists dataset_label text,
    add column if not exists rows jsonb,
    add column if not exists valuation_ok_count int,
    add column if not exists valuation_failed_count int;
