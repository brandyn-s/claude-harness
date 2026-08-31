// POSITIVE: should flag — unsafe block without // SAFETY: comment

fn read_raw_ptr(ptr: *const u8, len: usize) -> Vec<u8> {
    // BAD: unsafe without SAFETY comment
    unsafe {
        std::slice::from_raw_parts(ptr, len).to_vec()
    }
}

fn transmute_value<T>(val: u64) -> T {
    // BAD: unsafe without SAFETY comment
    unsafe { std::mem::transmute_copy(&val) }
}
