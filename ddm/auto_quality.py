"""海外直播自动画质：使用实际分片吞吐，降档快、升档留余量和稳定期。"""
AUTO_QUALITY = -1
OVERSEAS_PLATFORMS = ("twitch", "youtube")


class AutoQuality:
    def __init__(self, room_id, now):
        self.room_id = room_id
        self.last_switch = now
        self.stable_since = None
        self.stalled_since = None
        self.has_played = False

    def choose(self, options, current, network, state, now):
        tiers = [item for item in options if item["qn"] != AUTO_QUALITY]
        index = next((i for i, item in enumerate(tiers) if item["qn"] == current), None)
        if index is None:
            return None
        playing = state == "playing"
        if playing:
            self.has_played = True
            self.stalled_since = None
            if self.stable_since is None:
                self.stable_since = now
        else:
            self.stable_since = None
            if self.stalled_since is None:
                self.stalled_since = now
        if now - self.last_switch < 15:
            return None
        if not self.has_played and now - self.last_switch < 25:
            return None  # HLS 切档后的首次取片/解码缓冲不算播放卡顿
        rate, samples = network
        bandwidth = tiers[index].get("bandwidth", 0)
        slow = samples >= 2 and bandwidth > 0 and rate < bandwidth * 1.15
        stalled = self.stalled_since is not None and now - self.stalled_since >= 6
        target = index
        if (slow or stalled) and index + 1 < len(tiers):
            target = index + 1
            if slow:
                target = next((i for i in range(index + 1, len(tiers))
                    if 0 < tiers[i].get("bandwidth", 0) <= rate * .75), len(tiers) - 1)
        elif (playing and samples >= 3 and now - self.last_switch >= 30
              and now - self.stable_since >= 25):
            target = next((i for i in range(index)
                if 0 < tiers[i].get("bandwidth", 0) <= rate / 1.5), index)
        if target == index:
            return None
        self.last_switch = now
        self.stable_since = self.stalled_since = None
        return tiers[target]["qn"]
