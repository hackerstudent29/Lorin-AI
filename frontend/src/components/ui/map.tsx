import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

export type MapRef = maplibregl.Map;

export interface MapProps {
  center?: [number, number];
  zoom?: number;
  className?: string;
  styleUrl?: string;
}

export const Map = forwardRef<MapRef, MapProps>(
  (
    {
      center = [0, 0],
      zoom = 1,
      className = "",
      styleUrl = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    },
    ref
  ) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const mapRef = useRef<maplibregl.Map | null>(null);

    // Expose the MapLibre GL Map instance directly via ref
    useImperativeHandle(ref, () => mapRef.current as maplibregl.Map, []);

    useEffect(() => {
      if (!containerRef.current) return;

      const map = new maplibregl.Map({
        container: containerRef.current,
        style: styleUrl,
        center: center,
        zoom: zoom,
      });

      mapRef.current = map;

      return () => {
        map.remove();
        mapRef.current = null;
      };
    }, [styleUrl]);

    // Handle dynamic updates of center
    useEffect(() => {
      if (mapRef.current) {
        const currentCenter = mapRef.current.getCenter();
        if (currentCenter.lng !== center[0] || currentCenter.lat !== center[1]) {
          mapRef.current.setCenter(center);
        }
      }
    }, [center]);

    // Handle dynamic updates of zoom
    useEffect(() => {
      if (mapRef.current) {
        const currentZoom = mapRef.current.getZoom();
        if (currentZoom !== zoom) {
          mapRef.current.setZoom(zoom);
        }
      }
    }, [zoom]);

    return (
      <div
        ref={containerRef}
        className={`w-full h-full rounded-lg border border-slate-200 shadow-sm overflow-hidden ${className}`}
      />
    );
  }
);

Map.displayName = "Map";
