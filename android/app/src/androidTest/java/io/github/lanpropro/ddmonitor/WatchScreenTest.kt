package io.github.lanpropro.ddmonitor

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import org.junit.Rule
import org.junit.Test

class WatchScreenTest {
    @get:Rule val screen = createAndroidComposeRule<MainActivity>()

    @Test fun activityRecreationRetainsRoomInput() {
        screen.onNode(hasSetTextAction()).performTextInput("123")
        screen.activityRule.scenario.recreate()
        screen.onNode(hasSetTextAction()).assertTextContains("123")
    }

    @Test fun invalidRoomIsRejectedWithoutNetwork() {
        screen.onNodeWithText("B 站房间号").performTextInput("abc")
        screen.onNodeWithText("开始观看").performClick()
        screen.waitUntil(15000) {
            screen.onAllNodesWithText("请输入有效的 B 站直播间数字房间号").fetchSemanticsNodes().isNotEmpty()
        }
        screen.onNodeWithText("开始观看").assertIsEnabled()
        screen.onNodeWithText("停止").performClick()
        screen.onNodeWithText("请输入有效的 B 站直播间数字房间号").assertDoesNotExist()
    }
}
