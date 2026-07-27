-- L3–L4 research / market archive: enable RLS with public read, service write.
-- Writers use postgres/service_role (bypasses RLS); anon/authenticated read only.

ALTER TABLE IF EXISTS public.ref_exchange ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.ref_product ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.ref_contract ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.ref_trading_calendar ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.market_bar_archive ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.backtest_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.backtest_metric ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.factor_definition ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.factor_snapshot ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.config_version ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
  tbl text;
BEGIN
  FOREACH tbl IN ARRAY ARRAY[
    'ref_exchange', 'ref_product', 'ref_contract', 'ref_trading_calendar',
    'market_bar_archive', 'backtest_run', 'backtest_metric',
    'factor_definition', 'factor_snapshot', 'config_version'
  ]
  LOOP
    EXECUTE format(
      'DROP POLICY IF EXISTS %I ON public.%I',
      tbl || '_select_public',
      tbl
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR SELECT USING (true)',
      tbl || '_select_public',
      tbl
    );
  END LOOP;
END $$;
