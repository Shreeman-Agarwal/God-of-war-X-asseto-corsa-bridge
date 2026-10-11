package com.godwarbridge;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

final class VehicleMappingTest {
	private static final VehicleMapping.MappingOptions OPTIONS = new VehicleMapping.MappingOptions(
			new VehicleMapping.Position(100.0, 64.0, -50.0),
			new VehicleMapping.Position(10.0, 2.0, 20.0),
			2.0,
			1.0,
			-1.0,
			1.0,
			90.0
	);

	@Test
	void mapsPositionRelativeToCalibratedAnchorsAndScale() {
		VehicleMapping.Pose pose = VehicleMapping.map(
				new VehicleMapping.Position(12.0, 3.5, 18.0), 0.0, OPTIONS);
		assertEquals(104.0, pose.position().x(), 1.0e-9);
		assertEquals(67.0, pose.position().y(), 1.0e-9);
		assertEquals(-46.0, pose.position().z(), 1.0e-9);
		assertEquals(90.0, pose.yawDegrees(), 1.0e-9);
	}

	@Test
	void convertsAndWrapsHeading() {
		assertEquals(-170.0, VehicleMapping.map(
				OPTIONS.assettoCorsaOrigin(), Math.toRadians(100.0), OPTIONS).yawDegrees(), 1.0e-9);
		assertEquals(-180.0, VehicleMapping.wrapDegrees(540.0), 1.0e-9);
	}

	@Test
	void interpolationTakesShortestPathAcrossYawSeam() {
		VehicleMapping.Pose from = new VehicleMapping.Pose(new VehicleMapping.Position(0, 0, 0), 179.0);
		VehicleMapping.Pose to = new VehicleMapping.Pose(new VehicleMapping.Position(10, 2, -4), -179.0);
		VehicleMapping.Pose half = VehicleMapping.interpolate(from, to, 0.5);
		assertEquals(5.0, half.position().x(), 1.0e-9);
		assertEquals(1.0, half.position().y(), 1.0e-9);
		assertEquals(-180.0, half.yawDegrees(), 1.0e-9);
	}

	@Test
	void rejectsInvalidValuesAndUnsafeCoordinates() {
		assertThrows(IllegalArgumentException.class, () -> new VehicleMapping.MappingOptions(
				OPTIONS.minecraftAnchor(), OPTIONS.assettoCorsaOrigin(), Double.NaN, 1, 1, 1, 0));
		assertThrows(IllegalArgumentException.class, () -> VehicleMapping.map(
				new VehicleMapping.Position(100_001, 0, 0), 0, OPTIONS));
		assertThrows(IllegalArgumentException.class, () -> VehicleMapping.map(
				OPTIONS.assettoCorsaOrigin(), Double.POSITIVE_INFINITY, OPTIONS));
		assertThrows(IllegalArgumentException.class, () -> VehicleMapping.interpolate(
				new VehicleMapping.Pose(new VehicleMapping.Position(0, 0, 0), 0),
				new VehicleMapping.Pose(new VehicleMapping.Position(1, 0, 0), 0), 1.1));
	}

	@Test
	void detectsCoordinateJumps() {
		VehicleMapping.Pose first = new VehicleMapping.Pose(new VehicleMapping.Position(0, 0, 0), 0);
		VehicleMapping.Pose close = new VehicleMapping.Pose(new VehicleMapping.Position(20, 0, 0), 10);
		VehicleMapping.Pose jump = new VehicleMapping.Pose(new VehicleMapping.Position(200, 0, 0), 10);
		assertTrue(VehicleMapping.isPlausibleStep(first, close, 32));
		assertFalse(VehicleMapping.isPlausibleStep(first, jump, 32));
	}
}
