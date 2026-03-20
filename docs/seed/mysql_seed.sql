-- Sample MySQL seed data for MCP Gateway integration testing
-- Table: employees

CREATE TABLE IF NOT EXISTS employees (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL,
    department VARCHAR(100) NOT NULL,
    salary     DECIMAL(10, 2) NOT NULL,
    hired_on   DATE NOT NULL
);

INSERT INTO employees (name, department, salary, hired_on) VALUES
    ('Alice Johnson', 'Engineering', 95000.00, '2021-03-15'),
    ('Bob Smith',     'Marketing',   72000.00, '2020-06-01'),
    ('Carol White',   'Engineering', 102000.00,'2019-11-20'),
    ('Dave Brown',    'HR',           60000.00, '2022-01-10'),
    ('Eve Davis',     'Marketing',    78000.00, '2021-09-05'),
    ('Frank Miller',  'Engineering',  88000.00, '2022-07-18'),
    ('Grace Lee',     'HR',           65000.00, '2020-03-22'),
    ('Henry Chen',    'Marketing',    81000.00, '2023-02-14');

-- Table: projects

CREATE TABLE IF NOT EXISTS projects (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    owner_id    INT REFERENCES employees(id),
    status      ENUM('active', 'completed', 'on_hold') DEFAULT 'active',
    started_on  DATE NOT NULL,
    budget      DECIMAL(12, 2)
);

INSERT INTO projects (name, owner_id, status, started_on, budget) VALUES
    ('Platform Rewrite',   1, 'active',    '2024-01-01', 250000.00),
    ('Q2 Campaign',        2, 'completed', '2024-02-01',  50000.00),
    ('HR Portal',          4, 'active',    '2024-03-15',  30000.00),
    ('Data Pipeline',      3, 'on_hold',   '2024-01-20', 120000.00),
    ('Brand Refresh',      5, 'active',    '2024-04-01',  45000.00);
