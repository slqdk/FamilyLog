import { useEffect, useRef, useState } from 'react';
import maplibregl, { type GeoJSONSource, type MapMouseEvent } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { fmApi } from './api';
import { toGeoJSON } from './logic';
import type { FmCategories } from './types';

/** The map "Tilføj et sted" opens (2.47.0). Loaded only when opened - it is
    most of a megabyte of JavaScript the list page does not need.

    Every place in the database, clustered when zoomed out. The family's
    own reviewed places are bigger with a cream ring; wishlist places a sun
    ring. Tap a place: its page. Tap a cluster: zoom in. Tap anywhere else:
    a pin, and "Opret et nyt sted her" - one more tap, so a stray touch
    while panning does not start a form. Basemap: OpenFreeMap (OSM data,
    free, no key). */

const STYLE = 'https://tiles.openfreemap.org/styles/positron';
const REGION: [[number, number], [number, number]] = [[7.9, 53.3], [15.4, 57.9]];
export const CAT_COLOURS: Record<string, string> = {
  restaurant: '#b8643c', hotel: '#7b5ea7', city: '#5c6f87',
  playground: '#c9921f', activity: '#2f8a8f', attraction: '#b0476b', nature: '#4f7d4a',
};
const VIEW_KEY = 'fm.mapView';

export default function MapView({ cats, onOpen, onCreate }: {
  cats: FmCategories;
  onOpen: (id: number) => void;
  onCreate: (lat: number, lng: number) => void;
}) {
  const box = useRef<HTMLDivElement | null>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const pin = useRef<maplibregl.Marker | null>(null);
  const [picked, setPicked] = useState<{ lat: number; lng: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [count, setCount] = useState<number | null>(null);
  // Handlers read the latest callbacks without rebuilding the map.
  const cb = useRef({ onOpen, onCreate });
  cb.current = { onOpen, onCreate };

  useEffect(() => {
    if (!box.current) return;
    let saved: { center: [number, number]; zoom: number } | null = null;
    try { saved = JSON.parse(localStorage.getItem(VIEW_KEY) ?? 'null'); } catch { /* none */ }
    const m = new maplibregl.Map({
      container: box.current, style: STYLE,
      ...(saved ? { center: saved.center, zoom: saved.zoom } : { bounds: REGION }),
      attributionControl: { compact: true },
    });
    map.current = m;
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    const geo = new maplibregl.GeolocateControl({
      positionOptions: { enableHighAccuracy: true }, trackUserLocation: false,
      showUserLocation: true, fitBoundsOptions: { maxZoom: 14 },
    });
    m.addControl(geo, 'top-right');
    m.on('moveend', () => {
      const c = m.getCenter();
      try {
        localStorage.setItem(VIEW_KEY, JSON.stringify({ center: [c.lng, c.lat], zoom: m.getZoom() }));
      } catch { /* private mode */ }
    });
    m.on('error', (e) => {
      // Tile hiccups are normal; only say so when the style itself fails.
      if (!m.isStyleLoaded()) setError(`Kortet kunne ikke hentes (${e.error?.message ?? 'ukendt fejl'}).`);
    });

    m.on('load', async () => {
      if (!saved) { try { geo.trigger(); } catch { /* no permission */ } }
      let data;
      try { data = await fmApi.map(); } catch (e) {
        setError(e instanceof Error ? e.message : 'Stederne kunne ikke hentes.');
        return;
      }
      setCount(data.points.length);
      m.addSource('places', {
        type: 'geojson', data: toGeoJSON(data), cluster: true,
        clusterRadius: 48, clusterMaxZoom: 13,
      });
      m.addLayer({ id: 'clusters', type: 'circle', source: 'places', filter: ['has', 'point_count'],
        paint: {
          'circle-color': '#6c7b4b', 'circle-opacity': 0.88,
          'circle-stroke-color': '#f6f0e2', 'circle-stroke-width': 2,
          'circle-radius': ['step', ['get', 'point_count'], 15, 50, 19, 500, 24, 5000, 30],
        } });
      m.addLayer({ id: 'cluster-count', type: 'symbol', source: 'places', filter: ['has', 'point_count'],
        layout: { 'text-field': ['get', 'point_count_abbreviated'], 'text-size': 13,
                  'text-font': ['Noto Sans Bold'] },
        paint: { 'text-color': '#fbf8f0' } });
      // A spread of the colour table does not satisfy the expression type's
      // fixed-arity tuple, hence the cast.
      const colour = ['match', ['get', 'cat'], ...Object.entries(CAT_COLOURS).flat(),
                      '#4f7d4a'] as unknown as maplibregl.ExpressionSpecification;
      m.addLayer({ id: 'place', type: 'circle', source: 'places', filter: ['!', ['has', 'point_count']],
        paint: {
          'circle-color': colour,
          'circle-radius': ['case', ['get', 'reviewed'], 10, 7],
          'circle-stroke-width': ['case', ['get', 'reviewed'], 3.5, ['get', 'wished'], 3, 1.5],
          'circle-stroke-color': ['case', ['get', 'reviewed'], '#f6f0e2',
                                  ['get', 'wished'], '#e0b23f', '#fbf8f0'],
        } });
      m.addLayer({ id: 'place-name', type: 'symbol', source: 'places', minzoom: 14,
        filter: ['!', ['has', 'point_count']],
        layout: { 'text-field': ['get', 'name'], 'text-size': 12, 'text-offset': [0, 1.3],
                  'text-anchor': 'top', 'text-max-width': 9, 'text-font': ['Noto Sans Regular'],
                  'text-optional': true },
        paint: { 'text-color': '#37362c', 'text-halo-color': '#fbf8f0', 'text-halo-width': 1.5 } });

      // Generous targets: a finger is not a mouse pointer.
      const hit = (e: MapMouseEvent, layers: string[]) => {
        const p = e.point;
        return m.queryRenderedFeatures([[p.x - 12, p.y - 12], [p.x + 12, p.y + 12]], { layers });
      };
      m.on('click', async (e) => {
        const cluster = hit(e, ['clusters'])[0];
        if (cluster) {
          const src = m.getSource('places') as GeoJSONSource;
          const zoom = await src.getClusterExpansionZoom(cluster.properties.cluster_id as number);
          m.easeTo({ center: (cluster.geometry as GeoJSON.Point).coordinates as [number, number], zoom });
          return;
        }
        const place = hit(e, ['place'])[0];
        if (place) { cb.current.onOpen(Number(place.properties.id)); return; }
        const { lat, lng } = e.lngLat;
        pin.current?.remove();
        pin.current = new maplibregl.Marker({ color: '#56633a' }).setLngLat([lng, lat]).addTo(m);
        setPicked({ lat, lng });
      });
      m.on('mouseenter', 'place', () => { m.getCanvas().style.cursor = 'pointer'; });
      m.on('mouseleave', 'place', () => { m.getCanvas().style.cursor = ''; });
    });
    return () => { m.remove(); map.current = null; };
  }, []);

  const clearPin = () => { pin.current?.remove(); pin.current = null; setPicked(null); };

  return (
    <div className="fm-map-wrap">
      <div ref={box} className="fm-map" />
      <div className="fm-map-legend">
        {Object.entries(CAT_COLOURS).map(([k, c]) => (
          <span key={k}><i style={{ background: c }} />{cats[k]?.label ?? k}</span>
        ))}
        <span><i className="fm-legend-own" />I har anmeldt</span>
      </div>
      {error && <p className="fm-error fm-map-error">{error}</p>}
      {picked ? (
        <div className="fm-sheet fm-map-card">
          <p><strong>Nyt sted her?</strong> Tryk på et sted på kortet for at åbne det i stedet.</p>
          <div className="fm-map-card-row">
            <button className="fm-secondary" onClick={clearPin}>Fortryd</button>
            <button className="fm-primary" onClick={() => cb.current.onCreate(picked.lat, picked.lng)}>
              Opret et nyt sted her
            </button>
          </div>
        </div>
      ) : (
        <p className="fm-map-hint">
          {count == null ? 'Henter steder…'
            : 'Tryk på et sted for at anmelde det, eller på kortet for at oprette et nyt.'}
        </p>
      )}
    </div>
  );
}
