package io.github.lanpropro.ddmonitor

import android.os.Bundle
import android.util.Log
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView

@androidx.annotation.OptIn(UnstableApi::class)
class MainActivity : ComponentActivity() {
    private val model: WatchModel by viewModels()
    private var player by mutableStateOf<ExoPlayer?>(null)
    private var playbackListener: Player.Listener? = null
    private var playbackStatus by mutableStateOf("添加直播间，开始观看")
    private var urlIndex = 0
    private var liveWindowRetries = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT))
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(primary = Color(0xFF79DEBF),
                onPrimary = Color(0xFF003829), background = Color(0xFF10171E))) {
                val state by model.state.collectAsStateWithLifecycle()
                var room by rememberSaveable { mutableStateOf("") }
                LaunchedEffect(state.stream, player) {
                    urlIndex = 0
                    liveWindowRetries = 0
                    val stream = state.stream
                    if (stream == null) {
                        player?.stop()
                        player?.clearMediaItems()
                        playbackStatus = "添加直播间，开始观看"
                    } else play(stream)
                }
                Surface(Modifier.fillMaxSize()) {
                    BoxWithConstraints(Modifier.safeDrawingPadding().padding(20.dp)) {
                        val wide = maxWidth > maxHeight
                        val controls: @Composable () -> Unit = {
                            Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                                Text("DD监控室", style = MaterialTheme.typography.headlineMedium)
                                Text("安卓预览 · 单路观看", color = MaterialTheme.colorScheme.onSurfaceVariant)
                                OutlinedTextField(value = room, onValueChange = { room = it },
                                    label = { Text("B 站房间号") }, singleLine = true,
                                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                    modifier = Modifier.fillMaxWidth())
                                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                    Button(onClick = { model.watch(room) }, enabled = !state.loading) { Text("开始观看") }
                                    OutlinedButton(onClick = { model.stop() }) { Text("停止") }
                                }
                                if (state.loading) {
                                    LinearProgressIndicator(Modifier.fillMaxWidth())
                                    Text("正在获取直播…")
                                }
                                state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                                state.stream?.let { Text("房间 ${it.roomId}", style = MaterialTheme.typography.titleMedium) }
                                Text(playbackStatus, style = MaterialTheme.typography.bodyMedium)
                            }
                        }
                        val video: @Composable (Modifier) -> Unit = { modifier ->
                            Box(modifier.background(Color.Black), contentAlignment = Alignment.Center) {
                                AndroidView(factory = { context -> PlayerView(context).apply {
                                    setEnableComposeSurfaceSyncWorkaround(true)
                                } }, update = { it.player = player }, modifier = Modifier.fillMaxSize())
                                if (state.stream == null) Text("直播画面", color = Color(0xFF80909F))
                            }
                        }
                        if (wide) Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                            Box(Modifier.width(280.dp).fillMaxHeight().verticalScroll(rememberScrollState())) { controls() }
                            video(Modifier.weight(1f).fillMaxHeight())
                        } else Column(verticalArrangement = Arrangement.spacedBy(24.dp)) {
                            controls()
                            video(Modifier.fillMaxWidth().aspectRatio(16f / 9f))
                        }
                    }
                }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        player = ExoPlayer.Builder(this).build().also { instance ->
            val listener = object : Player.Listener {
                override fun onPlaybackStateChanged(state: Int) {
                    playbackStatus = when (state) {
                        Player.STATE_BUFFERING -> "正在缓冲…"
                        Player.STATE_READY -> "直播已就绪"
                        Player.STATE_ENDED -> "直播已结束，可点击开始观看重试"
                        else -> if (model.state.value.stream == null) "添加直播间，开始观看" else playbackStatus
                    }
                    Log.i("DDMonitorPlayback", "state=$state")
                }
                override fun onIsPlayingChanged(isPlaying: Boolean) {
                    if (isPlaying) playbackStatus = "正在播放"
                    else if (instance.playbackState == Player.STATE_READY) playbackStatus = "已暂停"
                    if (isPlaying) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    Log.i("DDMonitorPlayback", "playing=$isPlaying")
                }
                override fun onRenderedFirstFrame() { Log.i("DDMonitorPlayback", "first_frame") }
                override fun onPlayerError(error: PlaybackException) {
                    val stream = model.state.value.stream
                    if (error.errorCode == PlaybackException.ERROR_CODE_BEHIND_LIVE_WINDOW && liveWindowRetries < 2) {
                        liveWindowRetries++
                        playbackStatus = "正在恢复直播位置…"
                        instance.seekToDefaultPosition()
                        instance.prepare()
                    } else if (stream != null && urlIndex + 1 < stream.urls.size) {
                        urlIndex++
                        liveWindowRetries = 0
                        play(stream)
                    } else playbackStatus = "播放失败（${error.errorCodeName}），请重试"
                    Log.w("DDMonitorPlayback", "error=${error.errorCodeName}")
                }
            }
            playbackListener = listener
            instance.addListener(listener)
        }
    }

    private fun play(stream: LiveStream) {
        val http = DefaultHttpDataSource.Factory().setConnectTimeoutMs(12000).setReadTimeoutMs(12000)
            .setUserAgent(stream.headers["User-Agent"] ?: "DDMonitorAndroid")
            .setDefaultRequestProperties(stream.headers).setAllowCrossProtocolRedirects(true)
        val item = MediaItem.Builder().setUri(stream.urls[urlIndex])
            .setLiveConfiguration(MediaItem.LiveConfiguration.Builder()
                .setTargetOffsetMs(2500).setMaxPlaybackSpeed(1.02f).build()).build()
        val source = DefaultMediaSourceFactory(http).createMediaSource(item)
        player?.apply { setMediaSource(source); prepare(); playWhenReady = true }
    }

    override fun onStop() {
        val previous = player
        playbackListener?.let { previous?.removeListener(it) }
        playbackListener = null
        player = null
        previous?.release()
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        super.onStop()
    }
}
