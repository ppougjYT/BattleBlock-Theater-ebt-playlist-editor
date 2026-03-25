import argparse
import array
import os
import struct


WORD_ARRAY_TYPE = "L"
HEADER_SIZE = 48
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


if array.array(WORD_ARRAY_TYPE).itemsize != 4:
    raise RuntimeError("This script requires 32-bit unsigned long array items")


def load_key(path):
    key = array.array(WORD_ARRAY_TYPE)
    with open(path, "rb") as file_obj:
        file_obj.seek(0, os.SEEK_END)
        size = file_obj.tell()
        file_obj.seek(0, os.SEEK_SET)
        key.fromfile(file_obj, size // key.itemsize)
    return key


def resolve_local_path(name):
    return os.path.join(SCRIPT_DIR, name)


def load_hex_text(path):
    with open(path, "r", encoding="utf-8") as file_obj:
        tokens = file_obj.read().split()
    return bytes(int(token, 16) for token in tokens)


class MersenneTwister:
    def __init__(self):
        self.state = [0] * 624
        self.index = 0

    def seed(self, seed):
        self.index = 0
        self.state[0] = seed
        for i in range(1, 624):
            self.state[i] = (
                i + 0x6C078965 * (self.state[i - 1] ^ (self.state[i - 1] >> 30))
            ) & 0xFFFFFFFF

    def reseed(self):
        for i in range(624):
            y = (self.state[i] & 0x80000000) + (self.state[(i + 1) % 624] & 0x7FFFFFFF)
            self.state[i] = self.state[(i + 397) % 624] ^ (y >> 1)
            if y & 1:
                self.state[i] ^= 0x9908B0DF

    def next(self):
        if self.index == 0:
            self.reseed()
        y = self.state[self.index]
        y ^= y >> 11
        y ^= (y << 7) & 0x9D2C5680
        y ^= (y << 15) & 0xEFC60000
        y ^= y >> 18
        self.index = (self.index + 1) % 624
        return y


def get_rand_seed(name):
    seed = 0x19570320
    for index, char in enumerate(name):
        value = ord(char) >> (index & 3)
        seed = (seed * value + ord(char)) & 0xFFFFFFFF
    return seed


def get_file_key(name):
    rng = MersenneTwister()
    rng.seed(get_rand_seed(name))
    key = array.array(WORD_ARRAY_TYPE, [rng.next() for _ in range(4)])
    key.byteswap()
    return key


def feistel_word(k2, value):
    return (
        k2[(value & 0xFF) + 0x300]
        + (
            k2[((value >> 8) & 0xFF) + 0x200]
            ^ (k2[((value >> 16) & 0xFF) + 0x100] + k2[((value >> 24) & 0xFF)])
        )
    ) & 0xFFFFFFFF


class CipherState:
    def __init__(self, key1, key2, basename):
        self.key1 = array.array(WORD_ARRAY_TYPE, key1)
        self.key2 = array.array(WORD_ARRAY_TYPE, key2)
        self.file_key = get_file_key(basename)

    def encrypt_pair(self, a, b):
        v5 = a
        v4 = b
        for i in range(0, 16, 4):
            v1 = (v5 ^ self.key1[i + 0]) & 0xFFFFFFFF
            v2 = (v4 ^ self.key1[i + 1] ^ feistel_word(self.key2, v1)) & 0xFFFFFFFF
            v3 = (v1 ^ self.key1[i + 2] ^ feistel_word(self.key2, v2)) & 0xFFFFFFFF
            v4 = (v2 ^ self.key1[i + 3] ^ feistel_word(self.key2, v3)) & 0xFFFFFFFF
            v5 = (v3 ^ feistel_word(self.key2, v4)) & 0xFFFFFFFF
        return (v4 ^ self.key1[17]) & 0xFFFFFFFF, (v5 ^ self.key1[16]) & 0xFFFFFFFF

    def descramble(self):
        for i in range(len(self.key1)):
            self.key1[i] ^= self.file_key[i % len(self.file_key)]

        a = 0
        b = 0
        for i in range(0, len(self.key1), 2):
            a, b = self.encrypt_pair(a, b)
            self.key1[i + 0] = a
            self.key1[i + 1] = b
        for i in range(0, len(self.key2), 2):
            a, b = self.encrypt_pair(a, b)
            self.key2[i + 0] = a
            self.key2[i + 1] = b

    def encrypt_block(self, block8):
        a, b = struct.unpack("<LL", block8)
        x, y = self.encrypt_pair(a, b)
        return struct.pack("<LL", x, y)

    def decrypt_pair(self, a, b):
        v2 = a
        v3 = b
        v1 = 0

        for i in range(16):
            v1 = v2 ^ self.key1[17 - i]
            v2 = (v3 ^ feistel_word(self.key2, v1)) & 0xFFFFFFFF
            v3 = v1

        return (v1 ^ self.key1[0]) & 0xFFFFFFFF, (v2 ^ self.key1[1]) & 0xFFFFFFFF

    def decrypt_block(self, block8):
        a, b = struct.unpack("<LL", block8)
        x, y = self.decrypt_pair(a, b)
        return struct.pack("<LL", x, y)


def main():
    parser = argparse.ArgumentParser(description="Rebuild a BattleBlock Theater .ebt from a raw playlist hex dump.")
    parser.add_argument("input_hex", help="Rebuilt raw playlist hex dump text file")
    parser.add_argument("template_ebt", help="Original .ebt file to use as a template")
    parser.add_argument("output_ebt", help="Output rebuilt .ebt file")
    parser.add_argument("--basename", default="CAMPAIGN1", help="Basename used for the playlist key schedule")
    args = parser.parse_args()

    raw = load_hex_text(args.input_hex)
    template = open(args.template_ebt, "rb").read()

    if len(template) < HEADER_SIZE:
        raise ValueError("Template .ebt is too small")

    padded_raw = raw
    if len(padded_raw) % 8 != 0:
        padded_raw += b"\x00" * (8 - (len(padded_raw) % 8))

    encrypted_region_end = HEADER_SIZE + len(padded_raw)
    if encrypted_region_end > len(template):
        raise ValueError(
            f"Encrypted payload would exceed template size: need {encrypted_region_end}, have {len(template)}"
        )

    state = CipherState(load_key(resolve_local_path("key1")), load_key(resolve_local_path("key2")), args.basename.upper())
    state.descramble()

    out = bytearray(template)
    for offset in range(0, len(padded_raw), 8):
        block = padded_raw[offset:offset + 8]
        out[HEADER_SIZE + offset:HEADER_SIZE + offset + 8] = state.encrypt_block(block)

    with open(args.output_ebt, "wb") as file_obj:
        file_obj.write(out)

    print(f"Input raw bytes: {len(raw)}")
    print(f"Padded raw bytes: {len(padded_raw)}")
    print(f"Template size: {len(template)}")
    print(f"Wrote rebuilt ebt: {args.output_ebt}")


if __name__ == "__main__":
    main()
