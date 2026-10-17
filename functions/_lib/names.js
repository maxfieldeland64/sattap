// Server-assigned player names, e.g. "Misty Cumulus 42". Players never type a name, so a public
// board needs no moderation. ~30 x 30 x 90 = about 80,000 combinations.
const ADJECTIVES = [
  'Swift', 'Lofty', 'Misty', 'Breezy', 'Stormy', 'Sunny', 'Frosty', 'Hazy', 'Golden', 'Silent',
  'Brisk', 'Gentle', 'Bold', 'Cosmic', 'Orbital', 'Polar', 'Tropical', 'Arctic', 'Lucky', 'Curious',
  'Mighty', 'Quiet', 'Radiant', 'Windy', 'Dusty', 'Foggy', 'Gusty', 'Humid', 'Crisp', 'Twilight',
];
const NOUNS = [
  'Cumulus', 'Cirrus', 'Stratus', 'Nimbus', 'Typhoon', 'Monsoon', 'Squall', 'Zephyr', 'Jetstream',
  'Isobar', 'Aurora', 'Tundra', 'Mesa', 'Fjord', 'Atoll', 'Delta', 'Glacier', 'Canyon', 'Sahara',
  'Pampas', 'Steppe', 'Savanna', 'Geyser', 'Lagoon', 'Volcano', 'Equator', 'Meridian', 'Sextant',
  'Compass', 'Barometer',
];

const pick = (list) => list[crypto.getRandomValues(new Uint32Array(1))[0] % list.length];

export function randomName() {
  const n = 10 + (crypto.getRandomValues(new Uint32Array(1))[0] % 90);
  return `${pick(ADJECTIVES)} ${pick(NOUNS)} ${n}`;
}
