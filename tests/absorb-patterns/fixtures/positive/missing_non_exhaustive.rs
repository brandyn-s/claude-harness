// POSITIVE: should flag — public enum missing #[non_exhaustive]

// BAD: public enum without #[non_exhaustive]
#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("Not found: {0}")]
    NotFound(String),
    #[error("Database error: {0}")]
    Database(String),
    #[error("Internal error: {0}")]
    Internal(String),
}

// BAD: another public enum without it
#[derive(Debug, Clone)]
pub enum ConnectionState {
    Connected,
    Disconnected,
    Reconnecting,
}
