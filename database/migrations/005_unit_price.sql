-- =============================================================================
-- FORESIA - REVENUE MODEL UPGRADE
-- Migration 005: Add unit_price_aed to items and seed realistic values
-- =============================================================================

ALTER TABLE items ADD COLUMN IF NOT EXISTS unit_price_aed DECIMAL(10, 2) DEFAULT 10.00;

-- Update realistic prices for items
UPDATE items SET unit_price_aed = 45.00 WHERE id = 1;
UPDATE items SET unit_price_aed = 3.50 WHERE id = 2;
UPDATE items SET unit_price_aed = 18.00 WHERE id = 3;
UPDATE items SET unit_price_aed = 6.00 WHERE id = 4;
UPDATE items SET unit_price_aed = 8.50 WHERE id = 5;
UPDATE items SET unit_price_aed = 22.00 WHERE id = 6;
UPDATE items SET unit_price_aed = 16.00 WHERE id = 7;
UPDATE items SET unit_price_aed = 28.00 WHERE id = 8;
UPDATE items SET unit_price_aed = 5.00 WHERE id = 9;
UPDATE items SET unit_price_aed = 6.00 WHERE id = 10;
UPDATE items SET unit_price_aed = 18.50 WHERE id = 11;
UPDATE items SET unit_price_aed = 19.00 WHERE id = 12;
UPDATE items SET unit_price_aed = 8.00 WHERE id = 13;
UPDATE items SET unit_price_aed = 12.00 WHERE id = 14;
UPDATE items SET unit_price_aed = 9.50 WHERE id = 15;
UPDATE items SET unit_price_aed = 11.00 WHERE id = 16;
UPDATE items SET unit_price_aed = 24.00 WHERE id = 17;
UPDATE items SET unit_price_aed = 15.00 WHERE id = 18;
UPDATE items SET unit_price_aed = 14.50 WHERE id = 19;
UPDATE items SET unit_price_aed = 12.50 WHERE id = 20;
UPDATE items SET unit_price_aed = 14.00 WHERE id = 21;
UPDATE items SET unit_price_aed = 16.00 WHERE id = 22;
UPDATE items SET unit_price_aed = 14.00 WHERE id = 23;
UPDATE items SET unit_price_aed = 3.50 WHERE id = 24;
UPDATE items SET unit_price_aed = 68.00 WHERE id = 25;
UPDATE items SET unit_price_aed = 48.00 WHERE id = 26;
UPDATE items SET unit_price_aed = 11.50 WHERE id = 27;
UPDATE items SET unit_price_aed = 24.50 WHERE id = 28;
UPDATE items SET unit_price_aed = 9.00 WHERE id = 29;
UPDATE items SET unit_price_aed = 16.50 WHERE id = 30;
UPDATE items SET unit_price_aed = 55.00 WHERE id = 31;
UPDATE items SET unit_price_aed = 12.00 WHERE id = 32;
UPDATE items SET unit_price_aed = 32.00 WHERE id = 33;
UPDATE items SET unit_price_aed = 7.50 WHERE id = 34;
UPDATE items SET unit_price_aed = 7.50 WHERE id = 35;
UPDATE items SET unit_price_aed = 42.00 WHERE id = 36;
UPDATE items SET unit_price_aed = 38.00 WHERE id = 37;
UPDATE items SET unit_price_aed = 29.00 WHERE id = 38;
UPDATE items SET unit_price_aed = 35.00 WHERE id = 39;
UPDATE items SET unit_price_aed = 18.00 WHERE id = 40;
UPDATE items SET unit_price_aed = 25.00 WHERE id = 41;
UPDATE items SET unit_price_aed = 19.50 WHERE id = 42;
UPDATE items SET unit_price_aed = 6.00 WHERE id = 43;
UPDATE items SET unit_price_aed = 12.00 WHERE id = 44;
UPDATE items SET unit_price_aed = 14.00 WHERE id = 45;
UPDATE items SET unit_price_aed = 35.00 WHERE id = 46;
UPDATE items SET unit_price_aed = 15.00 WHERE id = 47;
UPDATE items SET unit_price_aed = 4.00 WHERE id = 48;
UPDATE items SET unit_price_aed = 6.00 WHERE id = 49;
UPDATE items SET unit_price_aed = 6.00 WHERE id = 50;
