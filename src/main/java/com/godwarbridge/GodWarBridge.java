package com.godwarbridge;

import net.fabricmc.api.ModInitializer;
import net.minecraft.resources.Identifier;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.atomic.AtomicReference;

public class GodWarBridge implements ModInitializer {
	public static final String MOD_ID = "godwarbridge";
	public static final Logger LOGGER = LoggerFactory.getLogger(MOD_ID);

	public record ACTelemetry(
			boolean connected,
			String senderStatus,
			double speedKmh,
			int rpm,
			int gear,
			double throttle,
			double brake,
			double steering,
			double heading,
			double acX,
			double acY,
			double acZ,
			int status,
			long physicsPacket,
			long telemetryAgeMillis,
			long receivedAtMillis
	) {
		public static ACTelemetry offline() {
			return new ACTelemetry(false, "sender_missing", 0, 0, 0, 0, 0, 0, 0,
					0, 0, 0, 0, 0, -1, 0);
		}
	}

	public static final AtomicReference<ACTelemetry> LATEST_TELEMETRY =
			new AtomicReference<>(ACTelemetry.offline());

	public static volatile String RECEIVER_STATUS = "connecting";

	@Override
	public void onInitialize() {
		BridgeCarEntityType.register();
		LOGGER.info("GodWarBridge initialized; the client will connect to the local telemetry sender.");
	}

	public static Identifier id(String path) {
		return Identifier.fromNamespaceAndPath(MOD_ID, path);
	}
}
