export function calibrateDripper(collectedMl: number, minutes: number): number | null {
  if (
    !Number.isFinite(collectedMl) ||
    !Number.isFinite(minutes) ||
    collectedMl <= 0 ||
    minutes <= 0
  )
    return null;
  return ((collectedMl / 1000) * 60) / minutes;
}
export interface ShotInputs {
  substrateL: number;
  plants: number;
  drippersPerPlant: number;
  flowLph: number;
  shotPercent: number;
}
export function previewShot(inputs: ShotInputs) {
  const { substrateL, plants, drippersPerPlant, flowLph, shotPercent } = inputs;
  if (
    ![substrateL, plants, drippersPerPlant, flowLph, shotPercent].every(Number.isFinite) ||
    substrateL <= 0 ||
    plants <= 0 ||
    drippersPerPlant <= 0 ||
    flowLph <= 0 ||
    shotPercent < 0 ||
    shotPercent > 100 ||
    !Number.isInteger(plants) ||
    !Number.isInteger(drippersPerPlant)
  )
    return null;
  const zoneSubstrateL = substrateL * plants,
    totalDrippers = plants * drippersPerPlant;
  const volumeL = (zoneSubstrateL * shotPercent) / 100;
  return {
    zoneSubstrateL,
    totalDrippers,
    volumeL,
    volumeMlPerPlant: substrateL * shotPercent * 10,
    durationSeconds: (volumeL / (totalDrippers * flowLph)) * 3600,
  };
}
