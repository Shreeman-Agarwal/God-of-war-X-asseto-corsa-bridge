package com.godwarbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.liy.blendlib.api.BlendModelKey;
import com.liy.blendlib.fabric.client.entity.BlendEntityRenderer;
import com.liy.blendlib.fabric.client.entity.BlendEntityRenderers;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.command.v2.ClientCommandManager;
import net.fabricmc.fabric.api.client.command.v2.ClientCommandRegistrationCallback;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.rendering.v1.hud.HudElementRegistry;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import com.mojang.brigadier.arguments.DoubleArgumentType;
import com.mojang.brigadier.arguments.IntegerArgumentType;
import net.minecraft.network.chat.Component;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.level.Level;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;

public class GodWarBridgeClient implements ClientModInitializer {
	private static final String TELEMETRY_HOST = "127.0.0.1";
	private static final int TELEMETRY_PORT = 47654;
	private static final int MAX_FRAME_BYTES = 4096;
	private static final long STALE_AFTER_MILLIS = 1500;
	private static final BlendModelKey VEHICLE_MODEL = BlendModelKey.parse("godwarbridge:pagani_huayra");

	private static volatile boolean hudVisible = true;
	private static volatile boolean vehicleVisible = true;
	private static volatile boolean debugEnabled;
	private static volatile double smoothingFactor = 0.35;
	private static volatile VehicleMapping.MappingOptions mapping;
	private static volatile VehicleMapping.Pose mappedPose;
	private static volatile String vehicleStatus = "run /gwb recenter to anchor vehicle";
	private static BridgeCarEntity vehicle;
	private static Level mappedLevel;
	private static VehicleMapping.Pose smoothedPose;
	private static boolean recenterRequired;

	@Override
	public void onInitializeClient() {
		BlendEntityRenderers.register(
				BridgeCarEntityType.TYPE,
				context -> BlendEntityRenderer.<BridgeCarEntity>builder(context, VEHICLE_MODEL)
						.staticRestPose()
						.shadowRadius(1.1F)
						.build()
		);

		HudElementRegistry.addLast(GodWarBridge.id("assetto_telemetry"), (graphics, deltaTracker) -> {
			if (hudVisible) {
				drawHud(graphics);
			}
		});
		ClientTickEvents.END_CLIENT_TICK.register(GodWarBridgeClient::tickVehicle);
		registerCommands();

		Thread receiver = new Thread(GodWarBridgeClient::receiveTelemetry, "GodWarBridge-TelemetryReceiver");
		receiver.setDaemon(true);
		receiver.start();
		GodWarBridge.LOGGER.info("GodWarBridge vehicle renderer and telemetry HUD registered.");
	}

	private static void drawHud(GuiGraphicsExtractor graphics) {
		Minecraft minecraft = Minecraft.getInstance();
		GodWarBridge.ACTelemetry data = GodWarBridge.LATEST_TELEMETRY.get();
		long age = data.receivedAtMillis() == 0 ? -1 : Math.max(0, System.currentTimeMillis() - data.receivedAtMillis());
		boolean dataFresh = age >= 0 && age <= STALE_AFTER_MILLIS;
		String acState = !"connected".equals(GodWarBridge.RECEIVER_STATUS)
				? "sender not connected"
				: dataFresh ? acStatusLabel(data.senderStatus(), data.status()) : "data stale / disconnected";
		int left = 10;
		int top = 10;
		int width = debugEnabled ? 330 : 305;
		int height = debugEnabled ? 186 : 168;
		graphics.fill(left, top, left + width, top + height, 0xB9000000);
		drawHudText(graphics, minecraft, "GODWARBRIDGE  |  LOCAL BRIDGE", left + 8, top + 7, 0xFF55FFAA);
		drawHudText(graphics, minecraft, "Bridge: " + bridgeLabel(), left + 8, top + 22, 0xFFFFFFFF);
		drawHudText(graphics, minecraft, "Assetto Corsa: " + acState, left + 8, top + 34, data.connected() && dataFresh ? 0xFF55FF55 : 0xFFFFAA55);
		drawHudText(graphics, minecraft, String.format("Speed %.1f km/h  RPM %d  Gear %d", data.speedKmh(), data.rpm(), data.gear()), left + 8, top + 46, 0xFFFFFFFF);
		drawHudText(graphics, minecraft, String.format("Throttle %.0f%%  Brake %.0f%%  Steer %.3f", data.throttle() * 100, data.brake() * 100, data.steering()), left + 8, top + 58, 0xFFFFFFFF);
		drawHudText(graphics, minecraft, String.format("AC yaw %.1f deg  Packet %d", Math.toDegrees(data.heading()), data.physicsPacket()), left + 8, top + 70, 0xFFDDDDFF);
		drawHudText(graphics, minecraft, String.format("AC position %.2f, %.2f, %.2f", data.acX(), data.acY(), data.acZ()), left + 8, top + 82, 0xFFDDDDFF);
		if (mappedPose != null) {
			VehicleMapping.Position pos = mappedPose.position();
			drawHudText(graphics, minecraft, String.format("Minecraft %.2f, %.2f, %.2f  yaw %.1f", pos.x(), pos.y(), pos.z(), mappedPose.yawDegrees()), left + 8, top + 94, 0xFFDDDDFF);
		} else {
			drawHudText(graphics, minecraft, "Minecraft position: not calibrated", left + 8, top + 94, 0xFFFFAA55);
		}
		drawHudText(graphics, minecraft, "Telemetry age: " + (age < 0 ? "no packets" : age + " ms"), left + 8, top + 106, 0xFFFFFFFF);
		drawHudText(graphics, minecraft, "Vehicle: " + (vehicleVisible ? vehicleStatus : "hidden"), left + 8, top + 118, 0xFFFFFFFF);
		drawHudText(graphics, minecraft, "BlendLib: renderer registered; use /blendlib inspect godwarbridge:pagani_huayra", left + 8, top + 130, 0xFFDDDDFF);
		drawHudText(graphics, minecraft, "Controls: /gwb recenter | show | hide | hud | map-scale | heading | debug", left + 8, top + 142, 0xFFBBBBBB);
		if (debugEnabled) {
			drawHudText(graphics, minecraft, "Receiver state: " + GodWarBridge.RECEIVER_STATUS, left + 8, top + 154, 0xFFBBBBBB);
			drawHudText(graphics, minecraft, "Model key: " + VEHICLE_MODEL.value() + " | mapping: " + (mapping == null ? "unset" : "calibrated"), left + 8, top + 166, 0xFFBBBBBB);
		}
	}

	private static String bridgeLabel() {
		return switch (GodWarBridge.RECEIVER_STATUS) {
			case "connected" -> "connected";
			case "invalid telemetry" -> "invalid telemetry (see latest log)";
		case "connecting" -> "connecting to 127.0.0.1:47654";
		default -> "sender not running; start tools/assetto_corsa_sender.py";
		};
	}

	private static String acStatusLabel(String senderStatus, int status) {
		return switch (senderStatus) {
			case "receiving" -> "LIVE (status " + status + ")";
			case "stale_ac_memory" -> "shared-memory data stale; restart AC session";
			case "waiting_for_ac" -> "waiting for AC live session";
			default -> "invalid sender state";
		};
	}

	private static void drawHudText(GuiGraphicsExtractor graphics, Minecraft minecraft, String text, int x, int y, int color) {
		graphics.text(minecraft.font, text, x, y, color, false);
	}

	private static void tickVehicle(Minecraft minecraft) {
		if (minecraft.level == null) {
			removeVehicle();
			mappedLevel = null;
			mapping = null;
			mappedPose = null;
			recenterRequired = false;
			vehicleStatus = "world disconnected; recenter after joining a world";
			return;
		}
		if (mappedLevel != minecraft.level) {
			removeVehicle();
			mapping = null;
			mappedPose = null;
			recenterRequired = false;
			mappedLevel = minecraft.level;
			vehicleStatus = "world changed; run /gwb recenter";
		}

		GodWarBridge.ACTelemetry telemetry = GodWarBridge.LATEST_TELEMETRY.get();
		long age = telemetry.receivedAtMillis() == 0 ? Long.MAX_VALUE : System.currentTimeMillis() - telemetry.receivedAtMillis();
		if (!vehicleVisible) {
			vehicleStatus = "hidden by user";
			removeVehicle();
			return;
		}
		if (!telemetry.connected() || age < 0 || age > STALE_AFTER_MILLIS) {
			vehicleStatus = age > STALE_AFTER_MILLIS ? "waiting for fresh telemetry" : "waiting for live AC session";
			mappedPose = null;
			removeVehicle();
			return;
		}
		if (mapping == null) {
			vehicleStatus = "not placed; run /gwb recenter";
			return;
		}
		if (recenterRequired) {
			vehicleStatus = "coordinate jump detected; run /gwb recenter";
			removeVehicle();
			return;
		}

		VehicleMapping.Pose target;
		try {
			target = VehicleMapping.map(
					new VehicleMapping.Position(telemetry.acX(), telemetry.acY(), telemetry.acZ()),
					telemetry.heading(),
					mapping
			);
		} catch (IllegalArgumentException exception) {
			vehicleStatus = "rejected unsafe telemetry coordinate";
			removeVehicle();
			return;
		}
		if (mappedPose != null && !VehicleMapping.isPlausibleStep(mappedPose, target, 64.0)) {
			recenterRequired = true;
			vehicleStatus = "coordinate jump detected; run /gwb recenter";
			removeVehicle();
			return;
		}
		mappedPose = target;
		smoothedPose = smoothedPose == null ? target : VehicleMapping.interpolate(smoothedPose, target, smoothingFactor);
		if (vehicle == null) {
			vehicle = new BridgeCarEntity(BridgeCarEntityType.TYPE, minecraft.level);
			vehicle.setNoGravity(true);
			minecraft.level.addEntity(vehicle);
		}
		vehicle.setPos(smoothedPose.position().x(), smoothedPose.position().y(), smoothedPose.position().z());
		vehicle.setYRot((float) smoothedPose.yawDegrees());
		vehicleStatus = "client-local entity active; asset readiness shown by /blendlib diagnostics";
	}

	private static void removeVehicle() {
		if (vehicle != null) {
			vehicle.discard();
			vehicle = null;
		}
		smoothedPose = null;
	}

	private static void registerCommands() {
		ClientCommandRegistrationCallback.EVENT.register((dispatcher, registryAccess) -> dispatcher.register(
				ClientCommandManager.literal("gwb")
						.then(ClientCommandManager.literal("show").executes(context -> {
							vehicleVisible = true;
						context.getSource().sendFeedback(Component.literal("GodWarBridge vehicle shown when live telemetry is available."));
							return 1;
						}))
						.then(ClientCommandManager.literal("hide").executes(context -> {
							vehicleVisible = false;
							removeVehicle();
							context.getSource().sendFeedback(Component.literal("GodWarBridge vehicle hidden."));
							return 1;
						}))
						.then(ClientCommandManager.literal("hud").executes(context -> {
							hudVisible = !hudVisible;
							context.getSource().sendFeedback(Component.literal("GodWarBridge HUD " + (hudVisible ? "shown" : "hidden") + "."));
							return 1;
						}))
						.then(ClientCommandManager.literal("recenter").executes(context -> recenter(context.getSource().getClient())))
						.then(ClientCommandManager.literal("map-scale")
								.then(ClientCommandManager.argument("blocksPerAcUnit", DoubleArgumentType.doubleArg(0.01, 16.0))
										.executes(context -> updateMapScale(context.getSource(), DoubleArgumentType.getDouble(context, "blocksPerAcUnit")))))
						.then(ClientCommandManager.literal("heading")
								.then(ClientCommandManager.argument("offsetDegrees", DoubleArgumentType.doubleArg(-3600, 3600))
										.executes(context -> updateHeading(context.getSource(), DoubleArgumentType.getDouble(context, "offsetDegrees")))))
						.then(ClientCommandManager.literal("axis-x")
								.then(ClientCommandManager.argument("sign", IntegerArgumentType.integer(-1, 1))
										.executes(context -> updateAxis(context.getSource(), "x", IntegerArgumentType.getInteger(context, "sign")))))
						.then(ClientCommandManager.literal("axis-z")
								.then(ClientCommandManager.argument("sign", IntegerArgumentType.integer(-1, 1))
										.executes(context -> updateAxis(context.getSource(), "z", IntegerArgumentType.getInteger(context, "sign")))))
						.then(ClientCommandManager.literal("yaw-sign")
								.then(ClientCommandManager.argument("sign", IntegerArgumentType.integer(-1, 1))
										.executes(context -> updateAxis(context.getSource(), "yaw", IntegerArgumentType.getInteger(context, "sign")))))
						.then(ClientCommandManager.literal("smoothing")
								.then(ClientCommandManager.argument("factor", DoubleArgumentType.doubleArg(0.05, 1.0))
										.executes(context -> updateSmoothing(context.getSource(), DoubleArgumentType.getDouble(context, "factor")))))
						.then(ClientCommandManager.literal("debug").executes(context -> {
							debugEnabled = !debugEnabled;
							context.getSource().sendFeedback(Component.literal("GodWarBridge diagnostics " + (debugEnabled ? "enabled" : "disabled") + "."));
							return 1;
						}))
		));
	}

	private static int recenter(Minecraft minecraft) {
		if (minecraft.player == null) {
			return 0;
		}
		GodWarBridge.ACTelemetry data = GodWarBridge.LATEST_TELEMETRY.get();
		if (!data.connected() || data.receivedAtMillis() == 0 || System.currentTimeMillis() - data.receivedAtMillis() > STALE_AFTER_MILLIS) {
			minecraft.player.sendSystemMessage(Component.literal("GodWarBridge needs fresh live AC telemetry before anchoring."));
			return 0;
		}
		VehicleMapping.MappingOptions previous = mapping;
		double yawSign = previous == null ? 1.0 : previous.yawSign();
		double headingOffset = VehicleMapping.wrapDegrees(minecraft.player.getYRot() - Math.toDegrees(data.heading()) * yawSign);
		mapping = new VehicleMapping.MappingOptions(
				new VehicleMapping.Position(minecraft.player.getX(), minecraft.player.getY(), minecraft.player.getZ()),
				new VehicleMapping.Position(data.acX(), data.acY(), data.acZ()),
				previous == null ? 1.0 : previous.blocksPerAcUnit(),
				previous == null ? 1.0 : previous.xAxisSign(),
				previous == null ? 1.0 : previous.zAxisSign(),
				yawSign, headingOffset
		);
		recenterRequired = false;
		mappedPose = null;
		smoothedPose = null;
		minecraft.player.sendSystemMessage(Component.literal("GodWarBridge anchor set at your current position. Use /gwb heading <degrees> to adjust orientation."));
		return 1;
	}

	private static int updateMapScale(net.fabricmc.fabric.api.client.command.v2.FabricClientCommandSource source, double scale) {
		if (mapping == null) {
			source.sendFeedback(Component.literal("Run /gwb recenter first."));
			return 0;
		}
		mapping = new VehicleMapping.MappingOptions(mapping.minecraftAnchor(), mapping.assettoCorsaOrigin(), scale,
				mapping.xAxisSign(), mapping.zAxisSign(), mapping.yawSign(), mapping.headingOffsetDegrees());
		mappedPose = null;
		smoothedPose = null;
		source.sendFeedback(Component.literal("GodWarBridge map scale set to " + scale + " blocks per AC unit."));
		return 1;
	}

	private static int updateHeading(net.fabricmc.fabric.api.client.command.v2.FabricClientCommandSource source, double offset) {
		if (mapping == null) {
			source.sendFeedback(Component.literal("Run /gwb recenter first."));
			return 0;
		}
		mapping = new VehicleMapping.MappingOptions(mapping.minecraftAnchor(), mapping.assettoCorsaOrigin(), mapping.blocksPerAcUnit(),
				mapping.xAxisSign(), mapping.zAxisSign(), mapping.yawSign(), offset);
		mappedPose = null;
		smoothedPose = null;
		source.sendFeedback(Component.literal("GodWarBridge heading offset set to " + offset + " degrees."));
		return 1;
	}

	private static int updateAxis(net.fabricmc.fabric.api.client.command.v2.FabricClientCommandSource source, String axis, int sign) {
		if (mapping == null) {
			source.sendFeedback(Component.literal("Run /gwb recenter first."));
			return 0;
		}
		if (sign != -1 && sign != 1) {
			source.sendFeedback(Component.literal("Axis and yaw signs must be -1 or 1."));
			return 0;
		}
		double xSign = axis.equals("x") ? sign : mapping.xAxisSign();
		double zSign = axis.equals("z") ? sign : mapping.zAxisSign();
		double yawSign = axis.equals("yaw") ? sign : mapping.yawSign();
		mapping = new VehicleMapping.MappingOptions(mapping.minecraftAnchor(), mapping.assettoCorsaOrigin(), mapping.blocksPerAcUnit(),
				xSign, zSign, yawSign, mapping.headingOffsetDegrees());
		mappedPose = null;
		smoothedPose = null;
		source.sendFeedback(Component.literal("GodWarBridge " + axis + " sign set to " + sign + "."));
		return 1;
	}

	private static int updateSmoothing(net.fabricmc.fabric.api.client.command.v2.FabricClientCommandSource source, double factor) {
		smoothingFactor = factor;
		source.sendFeedback(Component.literal("GodWarBridge interpolation factor set to " + factor + " (higher follows telemetry faster)."));
		return 1;
	}

	private static void receiveTelemetry() {
		while (!Thread.currentThread().isInterrupted()) {
			try (Socket socket = new Socket()) {
				socket.connect(new InetSocketAddress(TELEMETRY_HOST, TELEMETRY_PORT), 1000);
				socket.setSoTimeout(2500);
				socket.setKeepAlive(true);
				setReceiverStatus("connected");
				try (InputStream input = socket.getInputStream()) {
					while (!Thread.currentThread().isInterrupted()) {
						String line = readFrame(input);
						try {
							updateTelemetry(line);
							setReceiverStatus("connected");
						} catch (RuntimeException exception) {
							setReceiverStatus("invalid telemetry");
						}
					}
				}
			} catch (IOException exception) {
				setReceiverStatus("disconnected");
				GodWarBridge.LATEST_TELEMETRY.set(GodWarBridge.ACTelemetry.offline());
				try {
					TimeUnit.SECONDS.sleep(1);
				} catch (InterruptedException interrupted) {
					Thread.currentThread().interrupt();
				}
			}
		}
	}

	private static String readFrame(InputStream input) throws IOException {
		ByteArrayOutputStream bytes = new ByteArrayOutputStream(256);
		while (true) {
			int next = input.read();
			if (next < 0) {
				throw new IOException("Telemetry sender closed the stream");
			}
			if (next == '\n') {
				return bytes.toString(StandardCharsets.UTF_8);
			}
			if (next == '\r') {
				continue;
			}
			if (bytes.size() >= MAX_FRAME_BYTES) {
				throw new IOException("Telemetry frame exceeds " + MAX_FRAME_BYTES + " bytes");
			}
			bytes.write(next);
		}
	}

	private static void updateTelemetry(String json) {
		JsonObject object = JsonParser.parseString(json).getAsJsonObject();
		if (integer(object, "protocol_version", 1, 1) != 1) {
			throw new IllegalArgumentException("unsupported protocol_version");
		}
		String senderStatus = text(object, "sender_status");
		if (!senderStatus.equals("receiving") && !senderStatus.equals("waiting_for_ac") && !senderStatus.equals("stale_ac_memory")) {
			throw new IllegalArgumentException("unsupported sender_status");
		}
		int status = integer(object, "ac_status", 0, 3);
		boolean connected = bool(object, "connected");
		if (connected != (senderStatus.equals("receiving") && status == 2)) {
			throw new IllegalArgumentException("connected and sender_status/ac_status disagree");
		}
		JsonArray position = array(object, "ac_position");
		if (position.size() != 3) {
			throw new IllegalArgumentException("ac_position must contain exactly three values");
		}
		double x = finite(number(position.get(0), "ac_position.x"), "ac_position.x", -100_000, 100_000);
		double y = finite(number(position.get(1), "ac_position.y"), "ac_position.y", -100_000, 100_000);
		double z = finite(number(position.get(2), "ac_position.z"), "ac_position.z", -100_000, 100_000);
		int age = integer(object, "telemetry_age_ms", -1, 60_000);
		if (connected && (age < 0 || age > STALE_AFTER_MILLIS)) {
			throw new IllegalArgumentException("live telemetry age is outside the freshness bound");
		}
		GodWarBridge.LATEST_TELEMETRY.set(new GodWarBridge.ACTelemetry(
				connected,
			senderStatus,
			finite(number(object, "speed_kmh"), "speed_kmh", 0, 1000),
			integer(object, "rpm", 0, 30_000),
			integer(object, "gear_raw", -1, 20),
			finite(number(object, "throttle"), "throttle", 0, 1),
			finite(number(object, "brake"), "brake", 0, 1),
			finite(number(object, "steering"), "steering", -100, 100),
			finite(number(object, "heading"), "heading", -1000, 1000),
			x, y, z, status,
			integer(object, "physics_packet", 0, Integer.MAX_VALUE),
			age,
			System.currentTimeMillis()
		));
	}

	private static JsonArray array(JsonObject object, String key) {
		if (!object.has(key) || !object.get(key).isJsonArray()) {
			throw new IllegalArgumentException(key + " must be an array");
		}
		return object.getAsJsonArray(key);
	}

	private static String text(JsonObject object, String key) {
		if (!object.has(key) || !object.get(key).isJsonPrimitive() || !object.getAsJsonPrimitive(key).isString()) {
			throw new IllegalArgumentException(key + " must be a string");
		}
		return object.get(key).getAsString();
	}

	private static boolean bool(JsonObject object, String key) {
		if (!object.has(key) || !object.get(key).isJsonPrimitive() || !object.getAsJsonPrimitive(key).isBoolean()) {
			throw new IllegalArgumentException(key + " must be a boolean");
		}
		return object.get(key).getAsBoolean();
	}

	private static double number(JsonObject object, String key) {
		if (!object.has(key) || !object.get(key).isJsonPrimitive() || !object.getAsJsonPrimitive(key).isNumber()) {
			throw new IllegalArgumentException(key + " must be a number");
		}
		return object.get(key).getAsDouble();
	}

	private static double number(com.google.gson.JsonElement element, String key) {
		if (element == null || !element.isJsonPrimitive() || !element.getAsJsonPrimitive().isNumber()) {
			throw new IllegalArgumentException(key + " must be a number");
		}
		return element.getAsDouble();
	}

	private static int integer(JsonObject object, String key, int minimum, int maximum) {
		double value = number(object, key);
		if (!Double.isFinite(value) || value != Math.rint(value) || value < minimum || value > maximum) {
			throw new IllegalArgumentException(key + " must be an integer in [" + minimum + ", " + maximum + "]");
		}
		return (int) value;
	}

	private static double finite(double value, String key, double minimum, double maximum) {
		if (!Double.isFinite(value) || value < minimum || value > maximum) {
			throw new IllegalArgumentException(key + " is non-finite or outside its accepted range");
		}
		return value;
	}

	private static void setReceiverStatus(String status) {
		String previous = GodWarBridge.RECEIVER_STATUS;
		if (!previous.equals(status)) {
			GodWarBridge.RECEIVER_STATUS = status;
			if (status.equals("connected")) {
				GodWarBridge.LOGGER.info("Connected to localhost Assetto Corsa sender at {}:{}", TELEMETRY_HOST, TELEMETRY_PORT);
			} else if (status.equals("disconnected")) {
				GodWarBridge.LOGGER.warn("Assetto Corsa sender disconnected; reconnecting.");
			} else if (status.equals("invalid telemetry")) {
				GodWarBridge.LOGGER.warn("Telemetry protocol validation failed; waiting for a valid frame.");
			}
		}
	}
}
