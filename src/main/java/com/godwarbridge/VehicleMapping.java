package com.godwarbridge;

public final class VehicleMapping {
	public static final double MAX_AC_COORDINATE = 100_000.0;
	public static final double MAX_MINECRAFT_COORDINATE = 29_999_984.0;

	private VehicleMapping() {
	}

	public record Position(double x, double y, double z) {
		public Position {
			requireFinite(x, "x");
			requireFinite(y, "y");
			requireFinite(z, "z");
		}
	}

	public record Pose(Position position, double yawDegrees) {
		public Pose {
			if (position == null) {
				throw new IllegalArgumentException("position must not be null");
			}
			requireFinite(yawDegrees, "yawDegrees");
			yawDegrees = wrapDegrees(yawDegrees);
		}
	}

	public record MappingOptions(
			Position minecraftAnchor,
			Position assettoCorsaOrigin,
			double blocksPerAcUnit,
			double xAxisSign,
			double zAxisSign,
			double yawSign,
			double headingOffsetDegrees
	) {
		public MappingOptions {
			if (minecraftAnchor == null || assettoCorsaOrigin == null) {
				throw new IllegalArgumentException("Both mapping anchors are required");
			}
			requireFinite(blocksPerAcUnit, "blocksPerAcUnit");
			if (blocksPerAcUnit < 0.01 || blocksPerAcUnit > 16.0) {
				throw new IllegalArgumentException("blocksPerAcUnit must be between 0.01 and 16");
			}
			requireAxisSign(xAxisSign, "xAxisSign");
			requireAxisSign(zAxisSign, "zAxisSign");
			requireAxisSign(yawSign, "yawSign");
			requireFinite(headingOffsetDegrees, "headingOffsetDegrees");
		}
	}

	public static Pose map(Position acPosition, double acHeadingRadians, MappingOptions options) {
		if (acPosition == null || options == null) {
			throw new IllegalArgumentException("Telemetry position and mapping options are required");
		}
		requireFinite(acHeadingRadians, "acHeadingRadians");
		validateAcPosition(acPosition);

		Position origin = options.assettoCorsaOrigin();
		Position anchor = options.minecraftAnchor();
		double scale = options.blocksPerAcUnit();
		Position mapped = new Position(
				anchor.x() + (acPosition.x() - origin.x()) * scale * options.xAxisSign(),
				anchor.y() + (acPosition.y() - origin.y()) * scale,
				anchor.z() + (acPosition.z() - origin.z()) * scale * options.zAxisSign()
		);
		if (Math.abs(mapped.x()) > MAX_MINECRAFT_COORDINATE
				|| Math.abs(mapped.y()) > MAX_MINECRAFT_COORDINATE
				|| Math.abs(mapped.z()) > MAX_MINECRAFT_COORDINATE) {
			throw new IllegalArgumentException("Mapped position exceeds Minecraft's safe coordinate envelope");
		}

		double yaw = Math.toDegrees(acHeadingRadians) * options.yawSign()
				+ options.headingOffsetDegrees();
		return new Pose(mapped, yaw);
	}

	public static Pose interpolate(Pose from, Pose to, double alpha) {
		if (from == null || to == null) {
			throw new IllegalArgumentException("Both poses are required");
		}
		requireFinite(alpha, "alpha");
		if (alpha < 0.0 || alpha > 1.0) {
			throw new IllegalArgumentException("alpha must be between zero and one");
		}
		Position first = from.position();
		Position second = to.position();
		Position blendedPosition = new Position(
				lerp(first.x(), second.x(), alpha),
				lerp(first.y(), second.y(), alpha),
				lerp(first.z(), second.z(), alpha)
		);
		double yawDelta = wrapDegrees(to.yawDegrees() - from.yawDegrees());
		return new Pose(blendedPosition, from.yawDegrees() + yawDelta * alpha);
	}

	public static boolean isPlausibleStep(Pose from, Pose to, double maximumDistance) {
		if (from == null || to == null || !Double.isFinite(maximumDistance) || maximumDistance <= 0.0) {
			return false;
		}
		double dx = to.position().x() - from.position().x();
		double dy = to.position().y() - from.position().y();
		double dz = to.position().z() - from.position().z();
		return dx * dx + dy * dy + dz * dz <= maximumDistance * maximumDistance;
	}

	public static double wrapDegrees(double degrees) {
		requireFinite(degrees, "degrees");
		double wrapped = degrees % 360.0;
		if (wrapped >= 180.0) {
			wrapped -= 360.0;
		} else if (wrapped < -180.0) {
			wrapped += 360.0;
		}
		return wrapped;
	}

	private static void validateAcPosition(Position position) {
		if (Math.abs(position.x()) > MAX_AC_COORDINATE
				|| Math.abs(position.y()) > MAX_AC_COORDINATE
				|| Math.abs(position.z()) > MAX_AC_COORDINATE) {
			throw new IllegalArgumentException("Assetto Corsa position exceeds the accepted range");
		}
	}

	private static void requireAxisSign(double sign, String name) {
		requireFinite(sign, name);
		if (sign != -1.0 && sign != 1.0) {
			throw new IllegalArgumentException(name + " must be -1 or 1");
		}
	}

	private static double lerp(double from, double to, double alpha) {
		return from + (to - from) * alpha;
	}

	private static void requireFinite(double value, String name) {
		if (!Double.isFinite(value)) {
			throw new IllegalArgumentException(name + " must be finite");
		}
	}
}
