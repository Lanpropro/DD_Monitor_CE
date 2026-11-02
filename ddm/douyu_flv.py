"""Read-only incremental FLV/AVC header inspection; never persist media payloads."""
from collections import Counter


class FlvInspector:
    MAX_TAG = 4 * 1024 * 1024
    MAX_NALS = 4096

    def __init__(self, emit):
        self.emit = emit
        self.buffer = bytearray()
        self.header = False
        self.disabled = False
        self.offset = 0
        self.nal_length = None
        self.last_dts = {}
        self.last_idr = None
        self.base_dts = None
        self.counts = Counter()

    def fail(self, reason, **values):
        self.emit('flv.parse-error', offset=self.offset, reason=reason, **values)
        self.disabled = True
        self.buffer.clear()

    def feed(self, data):
        if self.disabled:
            return
        self.buffer.extend(data)
        if not self.header:
            if len(self.buffer) < 9:
                return
            if self.buffer[:3] != b'FLV':
                self.fail('not-flv')
                return
            if self.buffer[3] != 1:
                self.fail('unsupported-flv-version', version=self.buffer[3])
                return
            size = int.from_bytes(self.buffer[5:9], 'big')
            if not 9 <= size <= 4096:
                self.fail('invalid-header-size', size=size)
                return
            if len(self.buffer) < size + 4:
                return
            self.emit('flv.header', version=self.buffer[3], flags=self.buffer[4],
                      data_offset=size, previous_tag_size=int.from_bytes(self.buffer[size:size + 4], 'big'))
            del self.buffer[:size + 4]
            self.offset = size + 4
            self.header = True
        while len(self.buffer) >= 11:
            size = int.from_bytes(self.buffer[1:4], 'big')
            if size > self.MAX_TAG:
                self.fail('tag-exceeds-inspection-limit', size=size)
                return
            total = size + 15
            if len(self.buffer) < total:
                return
            kind = self.buffer[0]
            dts = int.from_bytes(self.buffer[4:7], 'big') | self.buffer[7] << 24
            payload = bytes(self.buffer[11:11 + size])
            previous = int.from_bytes(self.buffer[11 + size:total], 'big')
            row = dict(offset=self.offset, tag_type=kind, size=size, dts_ms=dts,
                       stream_id=int.from_bytes(self.buffer[8:11], 'big'),
                       previous_tag_size=previous, size_valid=previous == size + 11)
            if kind in (8, 9):
                if self.base_dts is None:
                    self.base_dts = dts
                row['relative_dts_ms'] = dts - self.base_dts
                prior = self.last_dts.get(kind)
                row['dts_delta_ms'] = None if prior is None else dts - prior
                self.last_dts[kind] = dts
            if kind == 9 and payload:
                row.update(self.video(payload, dts))
            elif kind == 8 and payload:
                row.update(audio_format=payload[0] >> 4,
                           aac_packet_type=payload[1] if payload[0] >> 4 == 10 and len(payload) > 1 else None)
            self.counts[kind] += 1
            self.emit('flv.tag', **row)
            del self.buffer[:total]
            self.offset += total
            if not row['size_valid']:
                # Do not fabricate subsequent packet boundaries after a corrupt tag.
                self.fail('previous-tag-size-mismatch', expected=size + 11, actual=previous)
                return

    def video(self, data, dts):
        row = {'frame_type': data[0] >> 4, 'codec_id': data[0] & 15}
        if data[0] & 128:
            row['inspection'] = 'enhanced-flv-not-parsed'
            return row
        if row['codec_id'] != 7 or len(data) < 5:
            row['inspection'] = 'not-avc-or-truncated'
            return row
        cts = int.from_bytes(data[2:5], 'big', signed=True)
        row.update(avc_packet_type=data[1], cts_ms=cts, pts_ms=dts + cts)
        if data[1] == 0:
            config = data[5:]
            if len(config) >= 5 and config[0] == 1:
                self.nal_length = (config[4] & 3) + 1
                row.update(nal_length_bytes=self.nal_length, avc_profile=config[1], avc_level=config[3])
                pos = 6
                try:
                    row['sps_count'] = config[5] & 31
                    for _ in range(row['sps_count']):
                        size = int.from_bytes(config[pos:pos + 2], 'big')
                        if len(config[pos:pos + 2]) != 2 or size == 0 or pos + 2 + size > len(config):
                            raise ValueError('SPS')
                        pos += 2 + size
                    row['pps_count'] = config[pos]
                    pos += 1
                    for _ in range(row['pps_count']):
                        size = int.from_bytes(config[pos:pos + 2], 'big')
                        if len(config[pos:pos + 2]) != 2 or size == 0 or pos + 2 + size > len(config):
                            raise ValueError('PPS')
                        pos += 2 + size
                except (IndexError, ValueError):
                    row['inspection'] = 'truncated-parameter-sets'
            else:
                row['inspection'] = 'invalid-avc-config'
        elif data[1] == 1:
            if self.nal_length is None:
                row['inspection'] = 'missing-avc-config'
                return row
            pos, types = 5, Counter()
            while pos < len(data):
                if sum(types.values()) >= self.MAX_NALS:
                    row['nal_error'] = 'inspection-nal-count-limit'
                    break
                if pos + self.nal_length > len(data):
                    row['nal_error'] = 'truncated-length'
                    break
                size = int.from_bytes(data[pos:pos + self.nal_length], 'big')
                pos += self.nal_length
                if size == 0 or pos + size > len(data):
                    row.update(nal_error='invalid-nal-size', declared_nal_size=size,
                               remaining_bytes=len(data) - pos)
                    break
                types[data[pos] & 31] += 1
                pos += size
            row['nal_types'] = dict(types)
            row['idr'] = bool(types[5])
            if row['idr']:
                row['idr_interval_ms'] = None if self.last_idr is None else dts - self.last_idr
                self.last_idr = dts
            row['since_idr_ms'] = None if self.last_idr is None else dts - self.last_idr
        return row

    def finish(self):
        self.emit('flv.summary', tags=dict(self.counts), unparsed_bytes=len(self.buffer),
                  inspected_bytes=self.offset, disabled=self.disabled)
