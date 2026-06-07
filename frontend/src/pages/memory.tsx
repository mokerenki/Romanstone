import { useState, useEffect, useCallback, useRef } from 'react';
import { ForceGraph2D } from 'react-force-graph'; // npm install react-force-graph
import { useQuery } from 'react-query'; // npm install react-query
import DatePicker from 'react-datepicker'; // npm install react-datepicker
import 'react-datepicker/dist/react-datepicker.css';
import { useForm, Controller } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as yup from 'yup';

interface Node { id: string; label: string; color?: string; properties?: any; } // Added properties
interface Link { source: string; target: string; label?: string; } // Added label
interface GraphData { nodes: Node[]; links: Link[]; }

// Schema for form validation
const memoryQuerySchema = yup.object().shape({
  mode: yup.string().oneOf(['semantic', 'graph', 'temporal']).required('Query mode is required'),
  query: yup.string().required('Query text is required'),
  entity_label: yup.string().when('mode', { is: 'temporal', then: yup.string().required('Entity label is required for temporal queries') }),
  entity_id: yup.string().when('mode', { is: 'temporal', then: yup.string().required('Entity ID is required for temporal queries') }),
  query_time: yup.date().when('mode', { is: 'temporal', then: yup.date().required('Query time is required for temporal queries') }),
  top_k: yup.number().integer().min(1).when('mode', { is: 'semantic', then: yup.number().default(5) }),
});

export default function MemoryExplorerPage() {
  const fgRef = useRef();
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);

  const { control, handleSubmit, watch, setValue, formState: { errors } } = useForm({
    resolver: yupResolver(memoryQuerySchema),
    defaultValues: {
      mode: 'semantic',
      query: '',
      entity_label: '',
      entity_id: '',
      query_time: new Date(),
      top_k: 5,
    },
  });

  const queryMode = watch('mode');

  const fetchMemory = useCallback(async (formData: typeof memoryQuerySchema.fields) => {
    const payload: any = { mode: formData.mode, query: formData.query };
    if (formData.mode === 'semantic') {
      payload.top_k = formData.top_k;
    } else if (formData.mode === 'temporal') {
      payload.entity_label = formData.entity_label;
      payload.entity_id = formData.entity_id;
      payload.query_time = formData.query_time.toISOString();
    }

    const response = await fetch('/api/agent/tools/memory_retriever', { // Assuming agent exposes tools via API
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.message || 'Failed to fetch memory data');
    }
    return response.json();
  }, []);

  const { data, isLoading, isError, error, refetch } = useQuery(
    ['memoryData', watch()], // Query key changes when form values change
    () => fetchMemory(watch()),
    { enabled: false } // Disable automatic fetching, trigger manually
  );

  useEffect(() => {
    if (data) {
      // Process data into graph format
      const newNodes: Node[] = [];
      const newLinks: Link[] = [];

      if (data.mode === 'semantic') {
        // Semantic search returns documents. Create nodes for them.
        data.results.forEach((item: any) => {
          newNodes.push({ id: item.event_id, label: item.content.substring(0, 50) + '...', color: 'blue', properties: item });
        });
      } else if (data.mode === 'graph') {
        // Graph query returns nodes and relationships directly
        // Assuming Kuzu query returns nodes with 'id' and 'label' and relationships with 'source', 'target', 'label'
        data.results.forEach((item: any) => {
          // Kuzu query results might be complex, need careful parsing
          // Example: if query returns nodes directly
          if (item.n && item.n.id) {
            newNodes.push({ id: item.n.id, label: item.n.id, color: 'green', properties: item.n });
          }
          // Example: if query returns relationships
          if (item.r && item.r.source && item.r.target) {
            newLinks.push({ source: item.r.source, target: item.r.target, label: item.r.type });
          }
        });
      } else if (data.mode === 'temporal') {
        // Temporal query returns a single fact. Represent as a node or highlight existing.
        if (data.result) {
          newNodes.push({ id: `${data.entity_id}-${data.query}`, label: `${data.entity_id}: ${data.query} = ${data.result}`, color: 'orange', properties: data });
        }
      }
      setGraphData({ nodes: newNodes, links: newLinks });
    }
  }, [data]);

  const handleNodeClick = useCallback((node: Node) => {
    setSelectedNode(node);
    // Center camera on clicked node
    // const distance = 40; // Example distance
    // const distRatio = 1 + distance/Math.hypot(node.x, node.y);
    // fgRef.current.cameraPosition(
    //   { x: node.x * distRatio, y: node.y * distRatio, z: fgRef.current.cameraPosition().z }, // new position
    //   node, // lookAt ({ x, y, z }) 
    //   3000  // ms transition duration
    // );
  }, []);

  const onSubmit = (formData: any) => {
    refetch(); // Trigger the query manually
  };

  return (
    <div className="max-w-7xl mx-auto p-8">
      <h1 className="text-3xl font-bold mb-6 text-white">Memory Explorer</h1>

      <form onSubmit={handleSubmit(onSubmit)} className="bg-gray-800 rounded-xl p-6 border border-gray-700 mb-6 grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-gray-300 text-sm font-bold mb-2">Query Mode:</label>
          <Controller
            name="mode"
            control={control}
            render={({ field }) => (
              <select {...field} className="w-full p-3 rounded-lg bg-gray-700 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500 text-white">
                <option value="semantic">Semantic Search</option>
                <option value="graph">Graph Query (Cypher)</option>
                <option value="temporal">Temporal Query</option>
              </select>
            )}
          />
          {errors.mode && <p className="text-red-500 text-xs italic mt-1">{errors.mode.message}</p>}
        </div>

        <div>
          <label className="block text-gray-300 text-sm font-bold mb-2">Query:</label>
          <Controller
            name="query"
            control={control}
            render={({ field }) => (
              <input
                {...field}
                type="text"
                placeholder={queryMode === 'semantic' ? 'Natural language query' : queryMode === 'graph' ? 'Cypher query (e.g., MATCH (n) RETURN n LIMIT 10)' : 'Property name (e.g., status)'}
                className="w-full p-3 rounded-lg bg-gray-700 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500 text-white"
              />
            )}
          />
          {errors.query && <p className="text-red-500 text-xs italic mt-1">{errors.query.message}</p>}
        </div>

        {queryMode === 'temporal' && (
          <>
            <div>
              <label className="block text-gray-300 text-sm font-bold mb-2">Entity Label:</label>
              <Controller
                name="entity_label"
                control={control}
                render={({ field }) => (
                  <input
                    {...field}
                    type="text"
                    placeholder="e.g., Case, Document"
                    className="w-full p-3 rounded-lg bg-gray-700 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500 text-white"
                  />
                )}
              />
              {errors.entity_label && <p className="text-red-500 text-xs italic mt-1">{errors.entity_label.message}</p>}
            </div>
            <div>
              <label className="block text-gray-300 text-sm font-bold mb-2">Entity ID:</label>
              <Controller
                name="entity_id"
                control={control}
                render={({ field }) => (
                  <input
                    {...field}
                    type="text"
                    placeholder="e.g., CASE-2023-001"
                    className="w-full p-3 rounded-lg bg-gray-700 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500 text-white"
                  />
                )}
              />
              {errors.entity_id && <p className="text-red-500 text-xs italic mt-1">{errors.entity_id.message}</p>}
            </div>
            <div>
              <label className="block text-gray-300 text-sm font-bold mb-2">Query Time:</label>
              <Controller
                name="query_time"
                control={control}
                render={({ field }) => (
                  <DatePicker
                    selected={field.value}
                    onChange={(date: Date) => field.onChange(date)}
                    showTimeSelect
                    dateFormat="Pp"
                    className="w-full p-3 rounded-lg bg-gray-700 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500 text-white"
                  />
                )}
              />
              {errors.query_time && <p className="text-red-500 text-xs italic mt-1">{errors.query_time.message}</p>}
            </div>
          </>
        )}

        {queryMode === 'semantic' && (
          <div>
            <label className="block text-gray-300 text-sm font-bold mb-2">Top K Results:</label>
            <Controller
              name="top_k"
              control={control}
              render={({ field }) => (
                <input
                  {...field}
                  type="number"
                  min="1"
                  className="w-full p-3 rounded-lg bg-gray-700 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500 text-white"
                />
              )}
            />
            {errors.top_k && <p className="text-red-500 text-xs italic mt-1">{errors.top_k.message}</p>}
          </div>
        )}

        <div className="md:col-span-2 flex justify-end">
          <button
            type="submit"
            className="px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-semibold text-white"
            disabled={isLoading}
          >
            {isLoading ? 'Searching...' : 'Execute Query'}
          </button>
        </div>
      </form>

      {isError && <div className="text-red-500 mb-4">Error: {error?.message}</div>}

      <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 h-[700px] relative">
        <h2 className="text-xl font-semibold mb-4 text-white">Knowledge Graph Visualization</h2>
        <ForceGraph2D
          ref={fgRef}
          graphData={graphData}
          nodeLabel="label"
          linkDirectionalArrowLength={3.5}
          linkDirectionalArrowRelPos={1}
          linkCurvature={0.25}
          onNodeClick={handleNodeClick}
          nodeCanvasObject={(node, ctx, globalScale) => {
            const label = node.label;
            const fontSize = 12/globalScale;
            ctx.font = `${fontSize}px Sans-Serif`;
            const textWidth = ctx.measureText(label).width;
            const bckgDimensions = [textWidth, fontSize].map(n => n + fontSize * 0.2); // some padding

            ctx.fillStyle = 'rgba(0, 0, 0, 0.8)';
            ctx.fillRect(node.x - bckgDimensions[0] / 2, node.y - bckgDimensions[1] / 2, ...bckgDimensions);
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = node.color || 'white';
            ctx.fillText(label, node.x, node.y);

            node.__bckgDimensions = bckgDimensions; // to re-use in nodePointerAreaPaint
          }}
          nodePointerAreaPaint={(node, color, ctx) => {
            ctx.fillStyle = color;
            const bckgDimensions = node.__bckgDimensions;
            bckgDimensions && ctx.fillRect(node.x - bckgDimensions[0] / 2, node.y - bckgDimensions[1] / 2, ...bckgDimensions);
          }}
          linkCanvasObject={(link, ctx, globalScale) => {
            const label = link.label;
            if (!label) return;

            const start = link.source;
            const end = link.target;

            // ignore if link not yet rendered
            if (typeof start !== 'object' || typeof end !== 'object') return;

            // calculate mid-point of the link
            const midx = (start.x + end.x) / 2;
            const midy = (start.y + end.y) / 2;

            // Draw text
            const fontSize = 8/globalScale;
            ctx.font = `${fontSize}px Sans-Serif`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = 'lightgrey';
            ctx.fillText(label, midx, midy);
          }}
        />

        {selectedNode && (
          <div className="absolute top-4 right-4 bg-gray-900 p-4 rounded-lg shadow-lg max-w-sm z-10 border border-gray-700">
            <h3 className="text-lg font-bold text-white mb-2">Node Details: {selectedNode.label}</h3>
            <p className="text-gray-300 text-sm mb-1">ID: {selectedNode.id}</p>
            {selectedNode.properties && (
              <div className="text-gray-300 text-sm">
                <h4 className="font-semibold mt-2">Properties:</h4>
                <pre className="bg-gray-800 p-2 rounded text-xs overflow-auto max-h-40">
                  {JSON.stringify(selectedNode.properties, null, 2)}
                </pre>
              </div>
            )}
            <button
              onClick={() => setSelectedNode(null)}
              className="mt-4 px-3 py-1 bg-red-600 hover:bg-red-700 rounded-lg text-sm font-semibold text-white"
            >
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  );
}