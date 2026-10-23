package com.ringpulse.app

import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** What `GET /nights/latest` returns, reduced to what the Today screen shows. */
data class NightInsights(
    val nightId: String,
    val syncStatus: String, // "complete" or "partial"
    val receivedPackets: Int,
    val totalPackets: Int,
    val missingPackets: List<Int>,
    val sleepScore: Int?,
    val readinessScore: Int?,
)

sealed interface FetchResult {
    data class Success(val night: NightInsights) : FetchResult
    object NoNightsYet : FetchResult
    data class Failure(val reason: String) : FetchResult
}

object RingPulseApi {
    // The Android emulator reaches the computer it runs on at 10.0.2.2.
    const val BASE_URL = "http://10.0.2.2:8000"

    /** Blocking call: run it off the main thread. Never throws; failures come back as [FetchResult.Failure]. */
    fun fetchLatestNight(baseUrl: String = BASE_URL): FetchResult {
        var connection: HttpURLConnection? = null
        return try {
            connection = URL("$baseUrl/nights/latest").openConnection() as HttpURLConnection
            connection.connectTimeout = 3_000
            connection.readTimeout = 5_000
            when (val code = connection.responseCode) {
                200 -> FetchResult.Success(parseNight(connection.inputStream.bufferedReader().readText()))
                404 -> FetchResult.NoNightsYet
                else -> FetchResult.Failure("Server error ($code)")
            }
        } catch (e: IOException) {
            FetchResult.Failure("Can't reach the server")
        } catch (e: JSONException) {
            FetchResult.Failure("Unexpected response from the server")
        } finally {
            connection?.disconnect()
        }
    }
}

fun parseNight(json: String): NightInsights {
    val obj = JSONObject(json)
    val missing = obj.getJSONArray("missing_packets")
    return NightInsights(
        nightId = obj.getString("night_id"),
        syncStatus = obj.getString("sync_status"),
        receivedPackets = obj.getInt("received_packets"),
        totalPackets = obj.getInt("total_packets"),
        missingPackets = List(missing.length()) { missing.getInt(it) },
        sleepScore = if (obj.isNull("sleep_score")) null else obj.getInt("sleep_score"),
        readinessScore = if (obj.isNull("readiness_score")) null else obj.getInt("readiness_score"),
    )
}
