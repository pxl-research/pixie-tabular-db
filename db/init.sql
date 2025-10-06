CREATE TABLE IF NOT EXISTS tabular_collections (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tabular_products (
    id BIGSERIAL PRIMARY KEY,
    collection_id BIGINT NOT NULL REFERENCES tabular_collections(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (collection_id, name)
);

CREATE TABLE IF NOT EXISTS tabular_documents (
    id BIGSERIAL PRIMARY KEY,
    file_name TEXT NOT NULL,
    file_hash VARCHAR(64) NOT NULL UNIQUE
        CONSTRAINT chk_filehash_len CHECK (length(file_hash) = 64),
    language TEXT,
    file_description TEXT,
    file_schema JSONB,
    attribute_descriptions JSONB,
    created_at timestamptz NOT NULL DEFAULT now()
    , UNIQUE (id, file_name)
);

CREATE TABLE IF NOT EXISTS tabular_rows (
    id BIGSERIAL PRIMARY KEY,
    file_id BIGINT NOT NULL REFERENCES tabular_documents(id) ON DELETE CASCADE,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tabular_collection_entries (
    collection_id BIGINT NOT NULL REFERENCES tabular_collections(id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL REFERENCES tabular_products(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    document_id BIGINT NOT NULL REFERENCES tabular_documents(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (document_id, file_name) REFERENCES tabular_documents(id, file_name),
    PRIMARY KEY (collection_id, product_id, file_name),
    UNIQUE (product_id, document_id)
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_rows_file_id ON tabular_rows(file_id);
CREATE INDEX IF NOT EXISTS idx_tce_document_id ON tabular_collection_entries(document_id);
CREATE INDEX IF NOT EXISTS idx_tce_product_id ON tabular_collection_entries(product_id);
