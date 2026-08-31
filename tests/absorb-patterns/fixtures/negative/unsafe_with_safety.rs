// NEGATIVE: should NOT flag — unsafe blocks have // SAFETY: comments

fn read_raw_ptr(ptr: *const u8, len: usize) -> Vec<u8> {
    // SAFETY: ptr is guaranteed valid for len bytes by the caller's contract,
    // and the data is Copy (u8), so no aliasing concerns.
    unsafe {
        std::slice::from_raw_parts(ptr, len).to_vec()
    }
}
