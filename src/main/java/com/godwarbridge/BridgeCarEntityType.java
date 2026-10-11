package com.godwarbridge;

import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.ResourceKey;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.MobCategory;
import net.minecraft.core.Registry;

public final class BridgeCarEntityType {
	public static final ResourceKey<EntityType<?>> KEY = ResourceKey.create(
			Registries.ENTITY_TYPE,
			GodWarBridge.id("bridge_car")
	);

	public static final EntityType<BridgeCarEntity> TYPE = Registry.register(
			BuiltInRegistries.ENTITY_TYPE,
			KEY,
			EntityType.Builder.<BridgeCarEntity>of(BridgeCarEntity::new, MobCategory.MISC)
					.sized(4.8F, 1.65F)
					.noSave()
					.noSummon()
					.build(KEY)
	);

	private BridgeCarEntityType() {
	}

	public static void register() {
		GodWarBridge.LOGGER.info("Registered client-local Assetto Corsa vehicle entity type.");
	}
}
