"""VietQR payload builder (NAPAS / EMVCo Merchant-Presented QR).

The string produced here is what every Vietnamese banking app expects when it
scans a transfer QR: the bank (BIN) and account are pre-filled, together with
the exact amount and the transfer note, so the shopper cannot mistype them and
staff can reconcile the payment by order code.
"""


def _tlv(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def crc16_ccitt(data: str) -> str:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) as required by EMVCo."""
    crc = 0xFFFF
    for byte in data.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def build_payload(bin_code: str, account_no: str, amount: int | None = None, note: str = "") -> str:
    account_no = "".join(ch for ch in account_no if ch.isalnum())
    beneficiary = _tlv("00", bin_code) + _tlv("01", account_no)
    merchant_info = _tlv("00", "A000000727") + _tlv("01", beneficiary) + _tlv("02", "QRIBFTTA")
    parts = [
        _tlv("00", "01"),
        _tlv("01", "12" if amount else "11"),  # 12 = dynamic (one-off amount), 11 = static
        _tlv("38", merchant_info),
        _tlv("53", "704"),  # VND
    ]
    if amount:
        parts.append(_tlv("54", str(int(amount))))
    parts.append(_tlv("58", "VN"))
    if note:
        parts.append(_tlv("62", _tlv("08", note[:25])))
    body = "".join(parts) + "6304"
    return body + crc16_ccitt(body)
