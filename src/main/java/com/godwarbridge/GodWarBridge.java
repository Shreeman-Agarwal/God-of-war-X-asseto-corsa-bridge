
package com.godwarbridge;

import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.event.player.UseBlockCallback;
import net.minecraft.resources.Identifier;
import net.minecraft.world.InteractionResult;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

public class GodWarBridge implements ModInitializer {
	public static final String MOD_ID = "godwarbridge";
	public static final Logger LOGGER = LoggerFactory.getLogger(MOD_ID);

	private static final String PYTHON_HOST = "127.0.0.1";
	private static final int PYTHON_PORT = 47653;

	private static final BlockingQueue<String> EVENTS =
			new LinkedBlockingQueue<>(1000);

	public record ACTelemetry(
			boolean connected,
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
			long physicsPacket
	) {
		public static ACTelemetry offline() {
			return new ACTelemetry(
					false, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
			);
		}
	}

	public static final AtomicReference<ACTelemetry> LATEST_TELEMETRY =
			new AtomicReference<>(ACTelemetry.offline());

	@Override
	public void onInitialize() {
		LOGGER.info("GodWarBridge is running!");

		Thread sender = new Thread(
				GodWarBridge::sendEventsToPython,
				"GodWarBridge-PythonSender"
		);
		sender.setDaemon(true);
		sender.start();

		UseBlockCallback.EVENT.register((player, world, hand, hitResult) -> {
			if (!world.isClientSide()) {
				var pos = hitResult.getBlockPos();
				String playerName = escapeJson(player.getName().getString());

				String event = String.format(
						"{\"event\":\"block_interaction\",\"player\":\"%s\",\"x\":%d,\"y\":%d,\"z\":%d}",
						playerName,
						pos.getX(),
						pos.getY(),
						pos.getZ()
				);

				if (!EVENTS.offer(event)) {
					LOGGER.warn("Python event queue is full; event dropped.");
				}
			}

			return InteractionResult.PASS;
		});
	}

	private static void sendEventsToPython() {
		while (!Thread.currentThread().isInterrupted()) {
			try {
				Socket socket = new Socket();
				socket.connect(
						new InetSocketAddress(PYTHON_HOST, PYTHON_PORT),
						2000
				);

				try (socket;
					 BufferedWriter writer = new BufferedWriter(
							 new OutputStreamWriter(
									 socket.getOutputStream(),
									 StandardCharsets.UTF_8
							 ))) {

					LOGGER.info("Connected to Python bridge at {}:{}",
							PYTHON_HOST, PYTHON_PORT);

					while (!Thread.currentThread().isInterrupted()) {
						String event = EVENTS.take();
						writer.write(event);
						writer.newLine();
						writer.flush();
					}
				}
			} catch (InterruptedException e) {
				Thread.currentThread().interrupt();
				break;
			} catch (IOException e) {
				LOGGER.warn(
						"Python bridge connection failed: {}. Retrying shortly.",
						e.getMessage()
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

	private static String escapeJson(String value) {
		return value
				.replace("\\", "\\\\")
				.replace("\"", "\\\"");
	}

	public static Identifier id(String path) {
		return Identifier.fromNamespaceAndPath(MOD_ID, path);
	}
}
