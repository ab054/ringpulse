package com.ringpulse.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import kotlin.concurrent.thread

/** Everything the Today screen shows, so it can be reasoned about (and tested) without any UI. */
data class TodayUiState(
    val night: NightInsights? = null, // the last night fetched successfully, kept while a new sync runs or fails
    val syncing: Boolean = false,
    val error: String? = null,
    val noNightsYet: Boolean = false,
)

val TodayUiState.badgeText: String
    get() = when {
        syncing -> "Syncing..."
        error != null -> "Sync failed"
        noNightsYet -> "No night yet"
        night == null -> "Not synced yet"
        night.syncStatus == "complete" -> "Synced"
        else -> "Partial sync (${night.missingPackets.size} missing)"
    }

fun TodayUiState.after(result: FetchResult): TodayUiState = when (result) {
    is FetchResult.Success -> TodayUiState(night = result.night)
    FetchResult.NoNightsYet -> TodayUiState(noNightsYet = true)
    is FetchResult.Failure -> copy(syncing = false, error = result.reason)
}

/**
 * The Today screen: two scores, a sync badge and a "Sync now" button.
 *
 * Every element has a stable accessibility id (its content description equals its test tag) so Appium
 * can find it without XPath: today_title, sleep_score, readiness_score, sync_badge, night_id,
 * error_message, sync_button. The displayed value is the element's text.
 */
@Composable
fun TodayScreen(fetch: () -> FetchResult = { RingPulseApi.fetchLatestNight() }) {
    var state by remember { mutableStateOf(TodayUiState()) }

    fun syncNow() {
        if (state.syncing) return
        state = state.copy(syncing = true, error = null)
        thread { state = state.after(fetch()) }
    }

    LaunchedEffect(Unit) { syncNow() }

    Column(
        modifier = Modifier.fillMaxSize().systemBarsPadding().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Today", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.tagged("today_title"))
        ScoreCard(title = "Sleep", value = state.night?.sleepScore.display(), tag = "sleep_score")
        ScoreCard(title = "Readiness", value = state.night?.readinessScore.display(), tag = "readiness_score")
        Text(state.badgeText, modifier = Modifier.tagged("sync_badge"))
        state.night?.let {
            Text(it.nightId, style = MaterialTheme.typography.bodySmall, modifier = Modifier.tagged("night_id"))
        }
        state.error?.let {
            Text(
                "$it. Tap Sync now to retry.",
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.tagged("error_message"),
            )
        }
        Button(onClick = { syncNow() }, enabled = !state.syncing, modifier = Modifier.tagged("sync_button")) {
            Text("Sync now")
        }
    }
}

@Composable
private fun ScoreCard(title: String, value: String, tag: String) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(value, style = MaterialTheme.typography.displayMedium, modifier = Modifier.tagged(tag))
        }
    }
}

private fun Int?.display(): String = this?.toString() ?: "--"

private fun Modifier.tagged(tag: String): Modifier = this.testTag(tag).semantics { contentDescription = tag }
