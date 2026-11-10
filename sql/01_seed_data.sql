-- ============================================================
-- Maritime Hypercare Agents — Seed data (simulated operational tables)
-- Run after 00_setup.sql. Creates 6 tables: ROUTES, PRICE_LISTS,
-- PRICE_LINES, QUOTES, BOOKINGS, TICKETS. All data is fictitious.
-- ============================================================

USE ROLE ACCOUNTADMIN;
USE DATABASE HYPERCARE_DB;
USE SCHEMA PUBLIC;
USE WAREHOUSE COMPUTE_WH;

-- ============================================================
-- 1. Routes
-- ============================================================

CREATE OR REPLACE TABLE ROUTES (
    route_id VARCHAR(20) PRIMARY KEY,
    pol VARCHAR(5) NOT NULL,
    pol_name VARCHAR(100),
    pod VARCHAR(5) NOT NULL,
    pod_name VARCHAR(100),
    service_line VARCHAR(50),
    transit_days INT,
    is_active BOOLEAN DEFAULT TRUE
);

INSERT INTO ROUTES VALUES
('RT-001','CNSHA','Shanghai','FRLEH','Le Havre','FAL EB',30,TRUE),
('RT-002','CNSHA','Shanghai','NLRTM','Rotterdam','FAL EB',28,TRUE),
('RT-003','CNSHA','Shanghai','DEHAM','Hamburg','FAL EB',32,TRUE),
('RT-004','FRLEH','Le Havre','CNSHA','Shanghai','FAL WB',31,TRUE),
('RT-005','SGSIN','Singapore','FRLEH','Le Havre','MEX3',25,TRUE),
('RT-006','SGSIN','Singapore','NLRTM','Rotterdam','MEX3',23,TRUE),
('RT-007','AEJEA','Jebel Ali','FRLEH','Le Havre','EPIC',18,TRUE),
('RT-008','AEJEA','Jebel Ali','NLRTM','Rotterdam','EPIC',16,TRUE),
('RT-009','CNSHA','Shanghai','MTMLA','Malta','FAL EB',22,TRUE),
('RT-010','BEANR','Antwerp','SGSIN','Singapore','AEX2',26,TRUE),
('RT-011','FRLEH','Le Havre','AEJEA','Jebel Ali','EPIC',17,TRUE),
('RT-012','NLRTM','Rotterdam','CNSHA','Shanghai','FAL WB',29,FALSE);

-- ============================================================
-- 2. Price Lists
-- ============================================================

CREATE OR REPLACE TABLE PRICE_LISTS (
    pricelist_id VARCHAR(20) PRIMARY KEY,
    pricelist_name VARCHAR(200),
    pricer_name VARCHAR(100),
    pricing_group VARCHAR(50),
    service_line VARCHAR(50),
    status VARCHAR(20) DEFAULT 'ACTIVE',
    created_at DATE,
    updated_at DATE
);

INSERT INTO PRICE_LISTS VALUES
('PL-001','Europe Import FAL Q1-2025','Marie Dupont','PG-EUR-IMP','FAL EB','ACTIVE','2025-01-05','2025-03-15'),
('PL-002','Europe Import FAL Q2-2025','Marie Dupont','PG-EUR-IMP','FAL EB','ACTIVE','2025-04-01','2025-06-10'),
('PL-003','Middle East Export EPIC','Ahmed Khan','PG-ME-EXP','EPIC','ACTIVE','2025-02-01','2025-05-20'),
('PL-004','Asia-Europe MEX3','Li Wei','PG-ASIA-EUR','MEX3','ACTIVE','2025-01-15','2025-04-30'),
('PL-005','Europe Import FAL Q4-2024','Marie Dupont','PG-EUR-IMP','FAL EB','EXPIRED','2024-10-01','2024-12-31'),
('PL-006','Intra-Med Q1-2025','Sofia Rossi','PG-MED','FAL EB','ACTIVE','2025-01-10','2025-03-28');

-- ============================================================
-- 3. Price Lines
-- ============================================================

CREATE OR REPLACE TABLE PRICE_LINES (
    line_id VARCHAR(20) PRIMARY KEY,
    pricelist_id VARCHAR(20) REFERENCES PRICE_LISTS(pricelist_id),
    route_id VARCHAR(20) REFERENCES ROUTES(route_id),
    container_type VARCHAR(10),
    commodity VARCHAR(50),
    rate_20 DECIMAL(10,2),
    rate_40 DECIMAL(10,2),
    rate_40hc DECIMAL(10,2),
    rate_45 DECIMAL(10,2),
    currency VARCHAR(3) DEFAULT 'USD',
    valid_from DATE,
    valid_to DATE,
    status VARCHAR(20),
    soc_flag BOOLEAN DEFAULT FALSE,
    nor_flag BOOLEAN DEFAULT FALSE,
    haz_flag BOOLEAN DEFAULT FALSE,
    charge_auto BOOLEAN DEFAULT FALSE,
    line_flexibility BOOLEAN DEFAULT FALSE,
    strategy VARCHAR(50)
);

INSERT INTO PRICE_LINES VALUES
('LN-001','PL-001','RT-001','20GP','FAK',1200.00,2200.00,2400.00,2800.00,'USD','2025-01-10','2025-03-31','CLO',FALSE,FALSE,FALSE,TRUE,FALSE,'STRAT_A'),
('LN-002','PL-001','RT-001','40HC','FAK',NULL,NULL,2500.00,NULL,'USD','2025-01-10','2025-03-31','CLO',FALSE,FALSE,FALSE,TRUE,TRUE,'STRAT_A'),
('LN-003','PL-001','RT-002','20GP','Electronics',1350.00,2450.00,2650.00,3050.00,'USD','2025-01-10','2025-03-31','CLO',FALSE,FALSE,FALSE,TRUE,FALSE,'STRAT_B'),
('LN-004','PL-001','RT-003','20GP','FAK',1280.00,2350.00,2550.00,2900.00,'USD','2025-01-10','2025-03-31','PNP',FALSE,FALSE,FALSE,FALSE,FALSE,NULL),
('LN-005','PL-002','RT-001','20GP','FAK',1250.00,2300.00,2500.00,2850.00,'USD','2025-04-01','2025-06-30','CLO',FALSE,FALSE,FALSE,TRUE,FALSE,'STRAT_A'),
('LN-006','PL-002','RT-002','40HC','Chemicals',NULL,NULL,2800.00,NULL,'USD','2025-04-01','2025-06-30','CLO',FALSE,FALSE,TRUE,TRUE,TRUE,'STRAT_B'),
('LN-007','PL-003','RT-007','20GP','FAK',950.00,1800.00,1950.00,2200.00,'USD','2025-02-01','2025-07-31','CLO',FALSE,FALSE,FALSE,TRUE,FALSE,'STRAT_A'),
('LN-008','PL-003','RT-008','20GP','Textiles',980.00,1850.00,2000.00,2250.00,'USD','2025-02-01','2025-07-31','CLO',FALSE,FALSE,FALSE,FALSE,TRUE,NULL),
('LN-009','PL-004','RT-005','20GP','FAK',1100.00,2050.00,2200.00,2500.00,'USD','2025-01-15','2025-06-30','CLO',FALSE,FALSE,FALSE,TRUE,FALSE,'STRAT_A'),
('LN-010','PL-004','RT-006','40HC','FAK',NULL,NULL,2150.00,NULL,'USD','2025-01-15','2025-06-30','PNP',FALSE,FALSE,FALSE,FALSE,FALSE,NULL),
('LN-011','PL-005','RT-001','20GP','FAK',1150.00,2100.00,2300.00,2700.00,'USD','2024-10-01','2024-12-31','EXP',FALSE,FALSE,FALSE,TRUE,FALSE,'STRAT_A'),
('LN-012','PL-006','RT-009','20GP','FAK',900.00,1700.00,1850.00,2100.00,'USD','2025-01-10','2025-03-31','CLO',FALSE,FALSE,FALSE,TRUE,FALSE,NULL),
('LN-013','PL-001','RT-001','20GP','Container',800.00,1500.00,1600.00,NULL,'USD','2025-01-10','2025-03-31','CLO',TRUE,FALSE,FALSE,FALSE,FALSE,NULL),
('LN-014','PL-002','RT-002','20GP','FAK',1300.00,2400.00,2600.00,2950.00,'USD','2025-04-01','2025-06-30','CLO',FALSE,FALSE,FALSE,TRUE,FALSE,'MARKET_ELASTICITY'),
('LN-015','PL-001','RT-001','40HC','Chemicals',NULL,NULL,2700.00,NULL,'USD','2025-02-01','2025-03-31','CLO',FALSE,FALSE,TRUE,TRUE,TRUE,'STRAT_B');

-- ============================================================
-- 4. Quotes
-- ============================================================

CREATE OR REPLACE TABLE QUOTES (
    quote_id VARCHAR(20) PRIMARY KEY,
    line_id VARCHAR(20) REFERENCES PRICE_LINES(line_id),
    route_id VARCHAR(20) REFERENCES ROUTES(route_id),
    customer_name VARCHAR(200),
    container_type VARCHAR(10),
    container_count INT,
    quoted_rate DECIMAL(10,2),
    currency VARCHAR(3) DEFAULT 'USD',
    quoted_at TIMESTAMP,
    valid_until TIMESTAMP,
    status VARCHAR(20),
    channel VARCHAR(20) DEFAULT 'SPOTON',
    special_equipment VARCHAR(50)
);

INSERT INTO QUOTES VALUES
('QT-001','LN-001','RT-001','Maersk Logistics','20GP',2,1200.00,'USD','2025-02-10 09:30:00','2025-02-17 23:59:59','ACCEPTED','SPOTON',NULL),
('QT-002','LN-003','RT-002','DHL Global','20GP',5,1350.00,'USD','2025-02-15 14:00:00','2025-02-22 23:59:59','ACCEPTED','SPOTON',NULL),
('QT-003','LN-005','RT-001','Kuehne+Nagel','20GP',3,1250.00,'USD','2025-04-05 10:00:00','2025-04-12 23:59:59','ACCEPTED','SPOTON',NULL),
('QT-004','LN-007','RT-007','DB Schenker','20GP',4,950.00,'USD','2025-03-20 08:15:00','2025-03-27 23:59:59','EXPIRED','SPOTON',NULL),
('QT-005','LN-005','RT-001','Bolloré Logistics','20GP',1,1320.00,'USD','2025-04-10 11:45:00','2025-04-17 23:59:59','ACCEPTED','SPOTON',NULL),
('QT-006','LN-006','RT-002','CEVA Logistics','40HC',2,2800.00,'USD','2025-05-01 16:00:00','2025-05-08 23:59:59','PENDING','SPOTON',NULL),
('QT-007','LN-014','RT-002','Expeditors','20GP',6,1300.00,'USD','2025-04-20 13:30:00','2025-04-27 23:59:59','ACCEPTED','SPOTON',NULL),
('QT-008','LN-009','RT-005','Agility','20GP',2,1100.00,'USD','2025-03-01 09:00:00','2025-03-08 23:59:59','ACCEPTED','SPOTON',NULL),
('QT-009','LN-001','RT-001','Panalpina','20GP',1,1350.00,'USD','2025-02-20 10:30:00','2025-02-27 23:59:59','ACCEPTED','SPOTON',NULL),
('QT-010','LN-012','RT-009','Geodis','20GP',3,900.00,'USD','2025-02-25 14:20:00','2025-03-04 23:59:59','ACCEPTED','SPOTON',NULL),
('QT-011','LN-011','RT-001','Nippon Express','20GP',2,1150.00,'USD','2024-11-15 08:00:00','2024-11-22 23:59:59','EXPIRED','SPOTON',NULL),
('QT-012','LN-015','RT-001','Hapag-Lloyd','40HC',1,2700.00,'USD','2025-02-12 15:00:00','2025-02-19 23:59:59','ACCEPTED','SPOTON',NULL);

-- ============================================================
-- 5. Bookings
-- ============================================================

CREATE OR REPLACE TABLE BOOKINGS (
    booking_id VARCHAR(20) PRIMARY KEY,
    quote_id VARCHAR(20) REFERENCES QUOTES(quote_id),
    route_id VARCHAR(20) REFERENCES ROUTES(route_id),
    customer_name VARCHAR(200),
    vessel_name VARCHAR(100),
    voyage_number VARCHAR(20),
    container_type VARCHAR(10),
    container_count INT,
    booked_rate DECIMAL(10,2),
    currency VARCHAR(3) DEFAULT 'USD',
    etd DATE,
    eta DATE,
    status VARCHAR(20),
    booked_at TIMESTAMP
);

INSERT INTO BOOKINGS VALUES
('BK-001','QT-001','RT-001','Maersk Logistics','CMA CGM MARCO POLO','FA125E','20GP',2,1200.00,'USD','2025-02-20','2025-03-22','CONFIRMED','2025-02-11 10:00:00'),
('BK-002','QT-002','RT-002','DHL Global','CMA CGM JULES VERNE','FA128E','20GP',5,1350.00,'USD','2025-02-25','2025-03-25','CONFIRMED','2025-02-16 09:30:00'),
('BK-003','QT-003','RT-001','Kuehne+Nagel','CMA CGM KERGUELEN','FA201E','20GP',3,1250.00,'USD','2025-04-15','2025-05-15','CONFIRMED','2025-04-06 11:00:00'),
('BK-004','QT-005','RT-001','Bolloré Logistics','CMA CGM MARCO POLO','FA205E','20GP',1,1320.00,'USD','2025-04-22','2025-05-22','PENDING','2025-04-11 08:45:00'),
('BK-005','QT-007','RT-002','Expeditors','CMA CGM JULES VERNE','FA210E','20GP',6,1300.00,'USD','2025-05-01','2025-05-29','CONFIRMED','2025-04-21 14:00:00'),
('BK-006','QT-008','RT-005','Agility','CMA CGM OTELLO','MX301N','20GP',2,1100.00,'USD','2025-03-10','2025-04-04','CONFIRMED','2025-03-02 10:15:00'),
('BK-007','QT-009','RT-001','Panalpina','CMA CGM KERGUELEN','FA130E','20GP',1,1350.00,'USD','2025-03-05','2025-04-04','CANCELLED','2025-02-21 09:00:00'),
('BK-008','QT-010','RT-009','Geodis','CMA CGM THALASSA','FA135E','20GP',3,900.00,'USD','2025-03-08','2025-03-30','CONFIRMED','2025-02-26 15:30:00'),
('BK-009','QT-012','RT-001','Hapag-Lloyd','CMA CGM MARCO POLO','FA127E','40HC',1,2700.00,'USD','2025-02-22','2025-03-24','CONFIRMED','2025-02-13 16:00:00');

-- ============================================================
-- 6. Tickets
-- ============================================================

CREATE OR REPLACE TABLE TICKETS (
    ticket_id VARCHAR(20) PRIMARY KEY,
    submitted_by VARCHAR(100),
    role VARCHAR(50),
    channel VARCHAR(20),
    subject VARCHAR(500),
    body TEXT,
    category VARCHAR(50),
    priority VARCHAR(20) DEFAULT 'NORMAL',
    status VARCHAR(20) DEFAULT 'OPEN',
    related_quote_id VARCHAR(20),
    related_booking_id VARCHAR(20),
    related_route_id VARCHAR(20),
    created_at TIMESTAMP,
    resolved_at TIMESTAMP,
    resolution_notes TEXT
);

INSERT INTO TICKETS VALUES
('TK-001','Jean Martin','STM','EMAIL','Price mismatch on Shanghai-Le Havre','The customer sees 1350 USD on SpotOn for 20GP FAK Shanghai to Le Havre but the pricer set it at 1200 in AQUA. Quote QT-009. Why is the displayed price different?','PRICE_MISMATCH','HIGH','OPEN','QT-009',NULL,'RT-001','2025-02-21 08:30:00',NULL,NULL),
('TK-002','Sophie Lemaire','STM','TEAMS','No offer visible for Jebel Ali to Le Havre','Client DB Schenker cannot see any offer on SpotOn for Jebel Ali to Le Havre 20GP. Quote QT-004 expired. Is there a new priceline?','NO_OFFER','NORMAL','OPEN','QT-004',NULL,'RT-007','2025-03-28 09:15:00',NULL,NULL),
('TK-003','Pierre Dubois','PRICER','EMAIL','Booking cannot be completed','Bolloré cannot finalize booking BK-004. It stays in PENDING status. The quote QT-005 was accepted and the rate matches. What is blocking the booking?','BOOKING_ISSUE','HIGH','OPEN','QT-005','BK-004','RT-001','2025-04-12 14:00:00',NULL,NULL),
('TK-004','Marie Dupont','PRICER','EMAIL','What rule applies for SOC empty containers?','A customer asked if empty SOC containers can be quoted on SpotOn. I set up a line LN-013 with SOC flag but the client says no offer appears. What rule applies?','RULE_QUESTION','NORMAL','OPEN',NULL,NULL,'RT-001','2025-02-18 11:00:00',NULL,NULL),
('TK-005','Ahmed Khan','PRICER','TEAMS','Strategy B not giving recommendations','I assigned Strategy B (MARKET_ELASTICITY) to line LN-014 but I am not getting any rate recommendations in the LMT. The line is CLO and valid. What could be wrong?','FUNCTIONALITY','NORMAL','OPEN',NULL,NULL,'RT-002','2025-04-22 16:30:00',NULL,NULL),
('TK-006','Li Wei','STM','EMAIL','Quote validity question','Customer Agility got quote QT-008 on March 1st. They want to book now on March 10th but the quote page says expired. Is the 7-day validity standard or configurable?','RULE_QUESTION','LOW','OPEN','QT-008','BK-006','RT-005','2025-03-10 07:45:00',NULL,NULL),
('TK-007','Jean Martin','STM','EMAIL','HAZ surcharge not applied','Quote QT-012 for 40HC chemicals on Shanghai-Le Havre does not show a HAZ surcharge. Line LN-015 has HAZ flag and charge_auto. Shouldn''t a surcharge appear?','PRICE_MISMATCH','HIGH','OPEN','QT-012','BK-009','RT-001','2025-02-14 10:20:00',NULL,NULL),
('TK-008','Sophie Lemaire','STM','TEAMS','Multiple tickets about Rotterdam pricing','This is the 3rd ticket this week about unexpected prices on the Shanghai-Rotterdam route. Customers see different rates than what pricers expect. Possible systemic issue?','RECURRING','HIGH','OPEN',NULL,NULL,'RT-002','2025-04-25 08:00:00',NULL,NULL),
('TK-009','Pierre Dubois','PRICER','EMAIL','Mass update not reflecting','I did a mass update on PL-002 to change rates for Q2 but the old rates still show on SpotOn. Is there a refresh delay?','FUNCTIONALITY','NORMAL','RESOLVED',NULL,NULL,NULL,'2025-04-02 13:00:00','2025-04-02 15:30:00','Mass update takes up to 2 hours to reflect on SpotOn. Confirmed rates updated after cache refresh.'),
('TK-010','Marie Dupont','PRICER','EMAIL','Charge auto vs line flexibility confusion','I enabled both charge_auto and line_flexibility on line LN-006 for HAZ chemicals. A customer reports they see a HAZ surcharge on their quote but they did not request HAZ goods. Which setting controls this?','RULE_QUESTION','NORMAL','OPEN',NULL,NULL,'RT-002','2025-05-02 09:30:00',NULL,NULL),
('TK-011','Sophie Lemaire','STM','TEAMS','No SpotOn offer for Le Havre to Shanghai','Customer reports no SpotOn offer displayed for FRLEH to CNSHA on My CMA. Rates appear filed and routing exists. Similar to TK-002 pattern.','NO_OFFER','MEDIUM','OPEN',NULL,NULL,'RT-002','2025-04-10 09:30:00',NULL,NULL);

-- ============================================================
-- Verification
-- ============================================================

SELECT 'ROUTES' AS tbl, COUNT(*) AS cnt FROM ROUTES
UNION ALL SELECT 'PRICE_LISTS', COUNT(*) FROM PRICE_LISTS
UNION ALL SELECT 'PRICE_LINES', COUNT(*) FROM PRICE_LINES
UNION ALL SELECT 'QUOTES', COUNT(*) FROM QUOTES
UNION ALL SELECT 'BOOKINGS', COUNT(*) FROM BOOKINGS
UNION ALL SELECT 'TICKETS', COUNT(*) FROM TICKETS
ORDER BY tbl;
