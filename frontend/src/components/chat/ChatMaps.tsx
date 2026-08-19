import { useState, useEffect } from "react";
import { Map, MapControls, MapMarker, MarkerContent, MarkerTooltip, MapRoute } from "@/components/ui/map";

const COLLEGE_COORDS: [number, number] = [80.2185, 12.8252]; // Lng, Lat

export function CollegeLocationMap() {
  return (
    <div className="h-[300px] w-full my-4 rounded-xl overflow-hidden border border-border">
      <Map center={COLLEGE_COORDS} zoom={13}>
        <MapControls position="top-right" showZoom showCompass showFullscreen />
        <MapMarker longitude={COLLEGE_COORDS[0]} latitude={COLLEGE_COORDS[1]}>
          <MarkerContent>
            <div className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-white bg-primary text-white shadow-lg shadow-black/20 transform transition-transform hover:scale-110">
              🎓
            </div>
          </MarkerContent>
          <MarkerTooltip>
            <div className="bg-background text-foreground px-2 py-1 rounded shadow text-sm">
              <strong className="block text-primary">MSAJCE</strong>
              Mohamed Sathak A.J. College of Engineering
            </div>
          </MarkerTooltip>
        </MapMarker>
      </Map>
    </div>
  );
}

export function CollegeRouteMap() {
  const [userCoords, setUserCoords] = useState<[number, number] | null>(null);
  const [route, setRoute] = useState<[number, number][]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if ("geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const coords: [number, number] = [position.coords.longitude, position.coords.latitude];
          setUserCoords(coords);
          fetchRoute(coords);
        },
        (err) => {
          console.error("Geolocation error:", err);
          setError("Could not get your location. Please ensure location permissions are granted.");
        }
      );
    } else {
      setError("Geolocation is not supported by your browser.");
    }
  }, []);

  const fetchRoute = async (start: [number, number]) => {
    try {
      const response = await fetch(
        `https://router.project-osrm.org/route/v1/driving/${start[0]},${start[1]};${COLLEGE_COORDS[0]},${COLLEGE_COORDS[1]}?overview=full&geometries=geojson`
      );
      const data = await response.json();
      if (data.code === "Ok" && data.routes.length > 0) {
        setRoute(data.routes[0].geometry.coordinates);
      } else {
        setError("Could not find a valid driving route.");
      }
    } catch (err) {
      console.error("Routing error:", err);
      setError("Error fetching route data.");
    }
  };

  if (error) {
    return (
      <div className="p-4 my-4 bg-red-500/10 text-red-500 rounded-lg border border-red-500/20 text-sm">
        📍 {error}
      </div>
    );
  }

  if (!userCoords) {
    return (
      <div className="p-8 my-4 bg-secondary/30 rounded-lg border border-border text-center text-sm animate-pulse flex flex-col items-center justify-center gap-2">
        <span className="text-2xl">📍</span>
        Getting your location to calculate directions...
      </div>
    );
  }

  return (
    <div className="h-[360px] w-full my-4 rounded-xl overflow-hidden border border-border relative">
      <Map center={userCoords} zoom={11}>
        <MapControls position="top-right" showZoom showFullscreen showLocate />
        
        {route.length > 0 && (
          <MapRoute coordinates={route} color="var(--primary)" width={5} opacity={0.8} />
        )}

        {/* User Marker */}
        <MapMarker longitude={userCoords[0]} latitude={userCoords[1]}>
          <MarkerContent>
            <div className="flex h-5 w-5 items-center justify-center rounded-full border-2 border-white bg-blue-500 shadow-lg"></div>
          </MarkerContent>
          <MarkerTooltip>
            <div className="bg-background px-2 py-1 rounded shadow text-sm">You are here</div>
          </MarkerTooltip>
        </MapMarker>

        {/* Destination Marker */}
        <MapMarker longitude={COLLEGE_COORDS[0]} latitude={COLLEGE_COORDS[1]}>
          <MarkerContent>
            <div className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-white bg-primary text-white shadow-lg">
              🎓
            </div>
          </MarkerContent>
          <MarkerTooltip>
            <div className="bg-background px-2 py-1 rounded shadow text-sm text-primary font-bold">MSAJCE</div>
          </MarkerTooltip>
        </MapMarker>
      </Map>
    </div>
  );
}
