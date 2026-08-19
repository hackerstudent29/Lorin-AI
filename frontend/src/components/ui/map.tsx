import React, { createContext, forwardRef, useContext, useEffect, useImperativeHandle, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { createPortal } from "react-dom";

export type MapRef = maplibregl.Map;

interface MapContextType {
  map: maplibregl.Map | null;
}

const MapContext = createContext<MapContextType>({ map: null });

export const useMap = () => useContext(MapContext);

export interface MapProps {
  center?: [number, number];
  zoom?: number;
  className?: string;
  styleUrl?: string;
  children?: React.ReactNode;
}

export const Map = forwardRef<MapRef, MapProps>(
  (
    {
      center = [0, 0],
      zoom = 1,
      className = "",
      styleUrl = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
      children
    },
    ref
  ) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const mapRef = useRef<maplibregl.Map | null>(null);
    const [mapLoaded, setMapLoaded] = useState(false);

    useImperativeHandle(ref, () => mapRef.current as maplibregl.Map, []);

    useEffect(() => {
      if (!containerRef.current) return;

      const map = new maplibregl.Map({
        container: containerRef.current,
        style: styleUrl,
        center: center,
        zoom: zoom,
      });

      map.on('load', () => {
        setMapLoaded(true);
      });

      mapRef.current = map;

      return () => {
        map.remove();
        mapRef.current = null;
        setMapLoaded(false);
      };
    }, [styleUrl]);

    // Handle dynamic updates of center
    useEffect(() => {
      if (mapRef.current && mapLoaded) {
        const currentCenter = mapRef.current.getCenter();
        if (currentCenter.lng !== center[0] || currentCenter.lat !== center[1]) {
          mapRef.current.flyTo({ center, zoom });
        }
      }
    }, [center, zoom, mapLoaded]);

    return (
      <MapContext.Provider value={{ map: mapLoaded ? mapRef.current : null }}>
        <div
          ref={containerRef}
          className={`relative w-full h-full rounded-lg border border-slate-200 shadow-sm overflow-hidden ${className}`}
        >
          {mapLoaded && children}
        </div>
      </MapContext.Provider>
    );
  }
);
Map.displayName = "Map";

export interface MapControlsProps {
  position?: "top-left" | "top-right" | "bottom-left" | "bottom-right";
  showZoom?: boolean;
  showCompass?: boolean;
  showLocate?: boolean;
  showFullscreen?: boolean;
}

export function MapControls({
  position = "top-right",
  showZoom = true,
  showCompass = true,
  showLocate = true,
  showFullscreen = true,
}: MapControlsProps) {
  const { map } = useMap();

  useEffect(() => {
    if (!map) return;

    const controls: maplibregl.IControl[] = [];

    if (showZoom || showCompass) {
      const nav = new maplibregl.NavigationControl({
        showCompass,
        showZoom,
      });
      map.addControl(nav, position);
      controls.push(nav);
    }

    if (showFullscreen) {
      const fs = new maplibregl.FullscreenControl();
      map.addControl(fs, position);
      controls.push(fs);
    }

    if (showLocate) {
      const geolocate = new maplibregl.GeolocateControl({
        positionOptions: { enableHighAccuracy: true },
        trackUserLocation: true,
      });
      map.addControl(geolocate, position);
      controls.push(geolocate);
    }

    return () => {
      controls.forEach((c) => {
        if (map.hasControl(c)) {
          map.removeControl(c);
        }
      });
    };
  }, [map, position, showZoom, showCompass, showLocate, showFullscreen]);

  return null;
}

const MarkerContext = createContext<{ setTooltip: (el: React.ReactNode) => void } | null>(null);

export interface MapMarkerProps {
  longitude: number;
  latitude: number;
  children?: React.ReactNode;
}

export function MapMarker({ longitude, latitude, children }: MapMarkerProps) {
  const { map } = useMap();
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [tooltip, setTooltip] = useState<React.ReactNode>(null);

  useEffect(() => {
    if (!map) return;

    const el = document.createElement("div");
    containerRef.current = el;

    const marker = new maplibregl.Marker({ element: el })
      .setLngLat([longitude, latitude])
      .addTo(map);

    markerRef.current = marker;

    return () => {
      marker.remove();
      markerRef.current = null;
      containerRef.current = null;
    };
  }, [map, longitude, latitude]);

  useEffect(() => {
    if (markerRef.current && tooltip && containerRef.current) {
      const popup = new maplibregl.Popup({
        offset: 25,
        closeButton: false,
        className: "custom-map-popup"
      }).setHTML(`<div class="px-2 py-1 text-sm font-medium"></div>`);
      
      markerRef.current.setPopup(popup);
    }
  }, [tooltip]);

  if (!containerRef.current) return null;

  return createPortal(
    <MarkerContext.Provider value={{ setTooltip }}>
      {children}
      {tooltip && (
        <div className="absolute opacity-0 pointer-events-none" ref={(el) => {
          if (el && markerRef.current) {
            const popup = markerRef.current.getPopup();
            if (popup) {
              popup.setDOMContent(el.cloneNode(true) as HTMLElement);
            }
          }
        }}>
          {tooltip}
        </div>
      )}
    </MarkerContext.Provider>,
    containerRef.current
  );
}

export function MarkerContent({ children }: { children: React.ReactNode }) {
  return <div className="cursor-pointer">{children}</div>;
}

export function MarkerTooltip({ children }: { children: React.ReactNode }) {
  const ctx = useContext(MarkerContext);
  useEffect(() => {
    if (ctx) ctx.setTooltip(children);
  }, [children, ctx]);
  return null;
}

export interface MapRouteProps {
  coordinates: [number, number][];
  color?: string;
  width?: number;
  opacity?: number;
}

export function MapRoute({ coordinates, color = "#3b82f6", width = 4, opacity = 0.8 }: MapRouteProps) {
  const { map } = useMap();
  const sourceId = useRef(`route-${Math.random().toString(36).substr(2, 9)}`).current;

  useEffect(() => {
    if (!map || coordinates.length < 2) return;

    const geojson: GeoJSON.Feature<GeoJSON.LineString> = {
      type: "Feature",
      properties: {},
      geometry: {
        type: "LineString",
        coordinates,
      },
    };

    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, {
        type: "geojson",
        data: geojson,
      });

      map.addLayer({
        id: `${sourceId}-layer`,
        type: "line",
        source: sourceId,
        layout: {
          "line-join": "round",
          "line-cap": "round",
        },
        paint: {
          "line-color": color,
          "line-width": width,
          "line-opacity": opacity,
        },
      });
      
      // Fit bounds
      const bounds = new maplibregl.LngLatBounds(coordinates[0], coordinates[0]);
      coordinates.forEach(coord => bounds.extend(coord as [number, number]));
      map.fitBounds(bounds, { padding: 40 });
    } else {
      (map.getSource(sourceId) as maplibregl.GeoJSONSource).setData(geojson);
    }

    return () => {
      if (map.getLayer(`${sourceId}-layer`)) {
        map.removeLayer(`${sourceId}-layer`);
      }
      if (map.getSource(sourceId)) {
        map.removeSource(sourceId);
      }
    };
  }, [map, coordinates, color, width, opacity, sourceId]);

  return null;
}
