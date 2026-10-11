
package com.godwarbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.rendering.v1.hud.HudElementRegistry;
import net.minecraft.client.Minecraft;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;

public class GodWarBridgeClient implements ClientModInitializer {
    private static final String PYTHON_HOST = "127.0.0.1";
    private static final int TELEMETRY_PORT = 47654;

    @Override
    public void onInitializeClient() {
        HudElementRegistry.addLast(
                GodWarBridge.id("assetto_telemetry"),
                (graphics, deltaTracker) -> {
                    GodWarBridge.ACTelemetry data =
                            GodWarBridge.LATEST_TELEMETRY.get();

                    Minecraft minecraft = Minecraft.getInstance();

                    int left = 10;
                    int top = 10;
                    int width = 230;
                    int lineHeight = 12;

                    graphics.fill(
                            left,
                            top,
                            left + width,
                            top + 116,
                            0xB9000000
                    );

                    graphics.drawString(
                            minecraft.font,
                            "GODW AR BRIDGE",
                            left + 8,
                            top + 7,
                            0xFF55FFAA
                    );

                    String connection = data.connected()
                            ? "AC: LIVE"
                            : "AC: WAITING FOR TELEMETRY";

                    graphics.drawString(
                            minecraft.font,
                            connection,
                            left + 8,
                            top + 22,
                            data.connected() ? 0xFF55FF55 : 0xFFFFAA55
                    );

                    graphics.drawString(
                            minecraft.font,
                            String.format("Speed: %.1f km/h", data.speedKmh()),
                            left + 8,
                            top + 37,
                            0xFFFFFFFF
                    );

                    graphics.drawString(
                            minecraft.font,
                            "RPM: " + data.rpm() + "   Gear raw: " + data.gear(),
                            left + 8,
                            top + 49,
                            0xFFFFFFFF
                    );

                    graphics.drawString(
                            minecraft.font,
                            String.format(
                                    "Throttle: %.0f%%   Brake: %.0f%%",
                                    data.throttle() * 100.0,
                                    data.brake() * 100.0
                            ),
                            left + 8,
                            top + 61,
                            0xFFFFFFFF
                    );

                    graphics.drawString(
                            minecraft.font,
                            String.format("Steering: %.3f", data.steering()),
                            left + 8,
                            top + 73,
                            0xFFFFFFFF
                    );

                    graphics.drawString(
                            minecraft.font,
                            String.format(
                                    "AC X: %.1f  Y: %.1f",
                                    data.acX(),
                                    data.acY()
                            ),
                            left + 8,
                            top + 85,
                            0xFFDDDDFF
                    );

                    graphics.drawString(
                            minecraft.font,
                            String.format(
                                    "AC Z: %.1f  Heading: %.3f",
                                    data.acZ(),
                                    data.heading()
                            ),
                            left + 8,
                            top + 97,
                            0xFFDDDDFF
                    );
                }
        );

        Thread receiver = new Thread(
                this::receiveTelemetry,
                "GodWarBridge-TelemetryReceiver"
        );
        receiver.setDaemon(true);
        receiver.start();

        GodWarBridge.LOGGER.info("GodWarBridge telemetry HUD registered.");
    }

    private void receiveTelemetry() {
        while (!Thread.currentThread().isInterrupted()) {
            try {
                Socket socket = new Socket();
                socket.connect(
                        new InetSocketAddress(PYTHON_HOST, TELEMETRY_PORT),
                        2000
                );
                socket.setKeepAlive(true);

                try (socket;
                     BufferedReader reader = new BufferedReader(
                             new InputStreamReader(
                                     socket.getInputStream(),
                                     StandardCharsets.UTF_8
                             ))) {

                    GodWarBridge.LOGGER.info(
                            "Connected to Python telemetry stream at {}:{}",
                            PYTHON_HOST,
                            TELEMETRY_PORT
                    );

                    String line;
                    while ((line = reader.readLine()) != null) {
                        try {
                            updateTelemetry(line);
                        } catch (RuntimeException e) {
                            GodWarBridge.LOGGER.warn(
                                    "Ignoring malformed telemetry message: {}",
                                    e.getMessage()
                            );
                        }
                    }
                }
            } catch (IOException e) {
                GodWarBridge.LATEST_TELEMETRY.set(
                        GodWarBridge.ACTelemetry.offline()
                );

                try {
                    TimeUnit.SECONDS.sleep(2);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    break;
                }
            }
        }
    }

    private void updateTelemetry(String json) {
        JsonObject object = JsonParser.parseString(json).getAsJsonObject();

        JsonArray position = object.has("ac_position")
                ? object.getAsJsonArray("ac_position")
                : new JsonArray();

        double x = position.size() > 0 ? position.get(0).getAsDouble() : 0;
        double y = position.size() > 1 ? position.get(1).getAsDouble() : 0;
        double z = position.size() > 2 ? position.get(2).getAsDouble() : 0;

        int status = getInt(object, "ac_status", 0);

        GodWarBridge.ACTelemetry telemetry =
                new GodWarBridge.ACTelemetry(
                        status == 2,
                        getDouble(object, "speed_kmh", 0),
                        getInt(object, "rpm", 0),
                        getInt(object, "gear_raw", 0),
                        getDouble(object, "throttle", 0),
                        getDouble(object, "brake", 0),
                        getDouble(object, "steering", 0),
                        getDouble(object, "heading", 0),
                        x,
                        y,
                        z,
                        status,
                        getLong(object, "physics_packet", 0)
                );

        GodWarBridge.LATEST_TELEMETRY.set(telemetry);
    }

    private static double getDouble(
            JsonObject object,
            String key,
            double fallback
    ) {
        return object.has(key) && !object.get(key).isJsonNull()
                ? object.get(key).getAsDouble()
                : fallback;
    }

    private static int getInt(
            JsonObject object,
            String key,
            int fallback
    ) {
        return object.has(key) && !object.get(key).isJsonNull()
                ? object.get(key).getAsInt()
                : fallback;
    }

    private static long getLong(
            JsonObject object,
            String key,
            long fallback
    ) {
        return object.has(key) && !object.get(key).isJsonNull()
                ? object.get(key).getAsLong()
                : fallback;
    }
}
