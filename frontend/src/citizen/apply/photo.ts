/**
 * Photos are resized and re-encoded on the device before upload, so a weak
 * connection sends at most 300 KB. Re-encoding through a canvas also drops the
 * EXIF block (camera model, time, location).
 */
export const MAX_PHOTO_BYTES = 300 * 1000;
const MAX_SIDE = 1600;
const MIN_SIDE = 480;

export interface PreparedPhoto {
  blob: Blob;
  /** The resized image, for an on-screen preview (a canvas needs no blob: URL, so the CSP stays strict). */
  canvas: HTMLCanvasElement;
}

function encode(canvas: HTMLCanvasElement, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
}

/** Decode, scale down and compress until the photo is at most MAX_PHOTO_BYTES. Throws if it cannot be read. */
export async function preparePhoto(file: Blob): Promise<PreparedPhoto> {
  if (typeof createImageBitmap !== 'function') throw new Error('no image decoder');
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
  try {
    let scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    for (let round = 0; round < 6; round += 1) {
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const context = canvas.getContext('2d');
      if (!context) throw new Error('no canvas');
      context.fillStyle = '#ffffff';
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      for (const quality of [0.82, 0.7, 0.58, 0.46]) {
        const blob = await encode(canvas, quality);
        if (blob && blob.size <= MAX_PHOTO_BYTES) return { blob, canvas };
      }
      if (Math.max(canvas.width, canvas.height) <= MIN_SIDE) break;
      scale *= 0.75;
    }
    throw new Error('photo too large');
  } finally {
    bitmap.close();
  }
}

/** Copy the prepared image into a visible canvas, scaled to its box. */
export function drawPreview(target: HTMLCanvasElement | null, source: HTMLCanvasElement | null): void {
  if (!target || !source) return;
  const width = Math.min(source.width, 640);
  target.width = width;
  target.height = Math.round((source.height / source.width) * width);
  target.getContext('2d')?.drawImage(source, 0, 0, target.width, target.height);
}
