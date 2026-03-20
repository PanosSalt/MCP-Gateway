-- Sample Postgres seed data for MCP Gateway integration testing
-- Table: products

CREATE TABLE IF NOT EXISTS products (
    id       SERIAL PRIMARY KEY,
    name     TEXT NOT NULL,
    category TEXT NOT NULL,
    price    NUMERIC(10, 2) NOT NULL,
    stock    INT DEFAULT 0
);

INSERT INTO products (name, category, price, stock) VALUES
    ('Laptop Pro 15',   'Electronics', 1299.99, 42),
    ('Wireless Mouse',  'Electronics',   29.99, 150),
    ('Standing Desk',   'Furniture',    499.00, 18),
    ('USB-C Hub',       'Electronics',   49.99, 90),
    ('Ergonomic Chair', 'Furniture',    349.00, 25),
    ('Monitor 27"',     'Electronics',  399.99, 60),
    ('Keyboard Pro',    'Electronics',   89.99, 80),
    ('Desk Lamp',       'Furniture',     45.00, 120);

-- Table: orders

CREATE TABLE IF NOT EXISTS orders (
    id         SERIAL PRIMARY KEY,
    product_id INT REFERENCES products(id),
    quantity   INT NOT NULL,
    ordered_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO orders (product_id, quantity, ordered_at) VALUES
    (1, 2, NOW() - INTERVAL '10 days'),
    (2, 5, NOW() - INTERVAL '9 days'),
    (1, 1, NOW() - INTERVAL '8 days'),
    (3, 1, NOW() - INTERVAL '7 days'),
    (4, 3, NOW() - INTERVAL '6 days'),
    (2, 2, NOW() - INTERVAL '5 days'),
    (6, 4, NOW() - INTERVAL '4 days'),
    (7, 6, NOW() - INTERVAL '3 days'),
    (5, 1, NOW() - INTERVAL '2 days'),
    (8, 8, NOW() - INTERVAL '1 day');
