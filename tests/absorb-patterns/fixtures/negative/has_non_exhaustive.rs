// NEGATIVE: should NOT flag — public enums have #[non_exhaustive]

// GOOD: has #[non_exhaustive]
#[non_exhaustive]
#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("Not found: {0}")]
    NotFound(String),
    #[error("Database error: {0}")]
    Database(String),
}

// GOOD: private enum doesn't need #[non_exhaustive]
#[derive(Debug)]
enum InternalState {
    Running,
    Stopped,
}

// GOOD: has #[non_exhaustive]
#[non_exhaustive]
#[derive(Debug, Clone)]
pub enum ConnectionState {
    Connected,
    Disconnected,
}
