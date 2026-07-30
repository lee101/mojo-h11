from std.sys.info import simd_width_of


comptime BPtr = UnsafePointer[UInt8, AnyOrigin[mut=True]]
comptime W = simd_width_of[DType.float64]()
comptime BYTE_W = W * 8


@export("mh11_find_crlf")
def find_crlf(addr: Int, n: Int, start: Int) abi("C") -> Int:
    if addr == 0 or n < 2:
        return -1
    var i = max(start, 0)
    if i > 0:
        i -= 1
    var data = BPtr(unsafe_from_address=addr)
    while i + 1 < n:
        if data[i] == 13 and data[i + 1] == 10:
            return i
        i += 1
    return -1


@export("mh11_find_headers_end")
def find_headers_end(addr: Int, n: Int, start: Int) abi("C") -> Int:
    if addr == 0 or n <= 0:
        return -1
    var data = BPtr(unsafe_from_address=addr)
    if data[0] == 10:
        return 1
    if n >= 2 and data[0] == 13 and data[1] == 10:
        return 2
    var i = max(start, 1)
    if i > 2:
        i -= 2
    while i + BYTE_W <= n:
        var candidates = data.load[width=BYTE_W](i).eq(10)
        if candidates.reduce_or():
            for j in range(BYTE_W):
                if data[i + j] == 10:
                    if data[i + j - 1] == 10:
                        return i + j + 1
                    if (
                        i + j >= 2
                        and data[i + j - 1] == 13
                        and data[i + j - 2] == 10
                    ):
                        return i + j + 1
        i += BYTE_W
    while i < n:
        if data[i] == 10:
            if data[i - 1] == 10:
                return i + 1
            if i >= 2 and data[i - 1] == 13 and data[i - 2] == 10:
                return i + 1
        i += 1
    return -1
