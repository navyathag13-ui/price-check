-- Gold serving tables for Azure SQL Database (free-offer General Purpose tier).
-- Deliberately only the precomputed marts + dimensions, NOT the 41.1M-row fact_price detail table --
-- see DECISIONS.md ADR-020 for why the full grain stays in Delta/DuckDB and only aggregates are served here.
IF OBJECT_ID('dbo.mart_price_comparison', 'U') IS NOT NULL DROP TABLE dbo.mart_price_comparison;
IF OBJECT_ID('dbo.dim_procedure_code', 'U') IS NOT NULL DROP TABLE dbo.dim_procedure_code;
IF OBJECT_ID('dbo.mart_hospital_quality', 'U') IS NOT NULL DROP TABLE dbo.mart_hospital_quality;
IF OBJECT_ID('dbo.dim_hospital', 'U') IS NOT NULL DROP TABLE dbo.dim_hospital;
GO

CREATE TABLE dbo.dim_hospital (
    hospital_slug         VARCHAR(64)   NOT NULL PRIMARY KEY,
    hospital_name         NVARCHAR(200) NOT NULL,
    state                 CHAR(2)       NULL,
    hospital_group        VARCHAR(32)   NULL,
    quality_as_of         DATE          NULL,
    quality_score         DECIMAL(5,1)  NULL,
    completeness          DECIMAL(6,4)  NULL,
    validity               DECIMAL(6,4)  NULL,
    consistency            DECIMAL(6,4)  NULL,
    freshness               DECIMAL(6,4)  NULL,
    days_since_last_update INT           NULL,
    loaded_at              DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

CREATE TABLE dbo.dim_procedure_code (
    code                 VARCHAR(32) COLLATE Latin1_General_100_CS_AS NOT NULL,   -- case-sensitive: real codes differ only by case
    code_type            VARCHAR(16)   NOT NULL,
    example_description  NVARCHAR(1000) NULL,
    hospital_count       INT           NOT NULL,
    price_row_count      BIGINT        NOT NULL,
    loaded_at             DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_dim_procedure_code PRIMARY KEY (code, code_type)
);
GO

CREATE TABLE dbo.mart_price_comparison (
    code                VARCHAR(32) COLLATE Latin1_General_100_CS_AS NOT NULL,
    code_type           VARCHAR(16)   NOT NULL,
    example_description NVARCHAR(1000) NULL,
    price_type          VARCHAR(16)   NOT NULL,
    n_prices             INT           NOT NULL,
    n_hospitals           INT           NOT NULL,
    n_payers               INT           NOT NULL,
    min_amount            DECIMAL(14,4) NOT NULL,
    median_amount         DECIMAL(14,4) NOT NULL,
    max_amount            DECIMAL(14,4) NOT NULL,
    stddev_amount         DECIMAL(14,4) NULL,
    n_flagged              INT           NOT NULL,
    loaded_at              DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_mart_price_comparison PRIMARY KEY (code, code_type, price_type)
);
CREATE INDEX IX_mart_price_comparison_code ON dbo.mart_price_comparison(code);
GO

CREATE TABLE dbo.mart_hospital_quality (
    hospital_slug          VARCHAR(64)   NOT NULL PRIMARY KEY,
    hospital_name          NVARCHAR(200) NOT NULL,
    state                  CHAR(2)       NULL,
    quality_score           DECIMAL(5,1)  NULL,
    completeness            DECIMAL(6,4)  NULL,
    validity                 DECIMAL(6,4)  NULL,
    consistency              DECIMAL(6,4)  NULL,
    freshness                 DECIMAL(6,4)  NULL,
    days_since_last_update   INT           NULL,
    total_prices              BIGINT        NOT NULL,
    flagged_prices            BIGINT        NOT NULL,
    pct_flagged                DECIMAL(6,2)  NOT NULL,
    loaded_at                  DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);
GO
