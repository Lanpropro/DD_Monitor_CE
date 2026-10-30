package io.github.lanpropro.ddmonitor

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.chaquo.python.Python
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

data class LiveStream(val roomId: String, val urls: List<String>, val headers: Map<String, String>, val quality: Int)
data class WatchState(val loading: Boolean = false, val error: String? = null, val stream: LiveStream? = null)

class WatchModel : ViewModel() {
    private val mutableState = MutableStateFlow(WatchState())
    val state = mutableState.asStateFlow()
    private var request: Job? = null

    fun watch(room: String) {
        request?.cancel()
        mutableState.value = WatchState(loading = true)
        request = viewModelScope.launch {
            try {
                val result = withContext(Dispatchers.IO) {
                    val text = Python.getInstance().getModule("bili_provider")
                        .callAttr("resolve_json", room).toString()
                    val json = JSONObject(text)
                    if (!json.getBoolean("ok")) throw IllegalArgumentException(json.getString("error"))
                    val urls = json.getJSONArray("urls")
                    val headers = json.getJSONObject("headers")
                    LiveStream(json.getString("room_id"), (0 until urls.length()).map { urls.getString(it) },
                        headers.keys().asSequence().associateWith { headers.getString(it) }, json.getInt("quality"))
                }
                mutableState.value = WatchState(stream = result)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: IllegalArgumentException) {
                mutableState.value = WatchState(error = error.message)
            } catch (_: Exception) {
                mutableState.value = WatchState(error = "获取直播失败，请稍后重试")
            }
        }
    }

    fun stop() {
        request?.cancel()
        mutableState.value = WatchState()
    }
}
