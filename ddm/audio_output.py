"""独立 WASAPI 输出的音量与立体声路由参数。"""


def linear_volume(volume: int) -> float:
    return 100 * (max(0, min(100, int(volume))) / 100) ** (1 / 3)


def channel_filters(channel: int) -> list[str]:
    if int(channel) == 5:
        return ["lavfi=[aresample=matrix_encoding=dplii]"]
    pan = {
        2: "stereo|c0=c1|c1=c0",
        3: "stereo|c0=0.5*c0+0.5*c1|c1=0*c1",
        4: "stereo|c0=0*c0|c1=0.5*c0+0.5*c1",
    }.get(int(channel))
    return [f"lavfi=[pan={pan}]"] if pan else []


def audio_filters(channel: int, normalize: bool = False) -> list[str]:
    filters = ["@ddm_meter:lavfi=[ebur128=metadata=1]",
               "@ddm_gain:lavfi=[volume=0dB]",
               "lavfi=[alimiter=limit=0.891251:level=false:latency=true]"] if normalize else []
    return filters + channel_filters(channel)
