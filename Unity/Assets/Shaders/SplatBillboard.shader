// Lightweight splat / point-cloud renderer for standalone Quest: every splat is a camera-facing disc
// (4 vertices sharing the splat center; the corner offset is applied in view space). Opaque with a
// circular clip, so no sorting is needed. Single-pass instanced / multiview safe.
//
// Vertex data (built by SplatView.cs):
//   POSITION  splat center (object space, Unity axes)
//   COLOR     splat color (sRGB bytes)
//   TEXCOORD0 corner in [-1, 1]^2
//   TEXCOORD1 x = radius in object-space meters
Shader "Understory/SplatBillboard"
{
    Properties
    {
        _SizeMultiplier ("Size multiplier", Float) = 1.5
    }
    SubShader
    {
        Tags { "RenderType" = "TransparentCutout" "Queue" = "AlphaTest" "RenderPipeline" = "UniversalPipeline" }

        Pass
        {
            Name "SplatUnlit"
            Tags { "LightMode" = "UniversalForward" }
            Cull Off
            ZWrite On

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            CBUFFER_START(UnityPerMaterial)
                float _SizeMultiplier;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                half4 color : COLOR;
                float2 corner : TEXCOORD0;
                float2 radius : TEXCOORD1;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                half4 color : COLOR;
                float2 corner : TEXCOORD0;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            Varyings vert(Attributes input)
            {
                Varyings output;
                UNITY_SETUP_INSTANCE_ID(input);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);

                float3 centerWS = TransformObjectToWorld(input.positionOS.xyz);
                // Object scale (the tabletop shrinks the room), so discs shrink with it.
                float objectScale = length(float3(UNITY_MATRIX_M._m00, UNITY_MATRIX_M._m10, UNITY_MATRIX_M._m20));
                float3 centerVS = TransformWorldToView(centerWS);
                centerVS.xy += input.corner * input.radius.x * objectScale * _SizeMultiplier;
                output.positionCS = TransformWViewToHClip(centerVS);

                half3 rgb = input.color.rgb;
                #if !defined(UNITY_COLORSPACE_GAMMA)
                // sRGB -> linear (fast polynomial fit; avoids depending on Color.hlsl)
                rgb = rgb * (rgb * (rgb * 0.305306011 + 0.682171111) + 0.012522878);
                #endif
                output.color = half4(rgb, 1);
                output.corner = input.corner;
                return output;
            }

            half4 frag(Varyings input) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(input);
                float r2 = dot(input.corner, input.corner);
                clip(1.0 - r2);
                half shade = 1.0 - 0.3 * r2; // a little falloff toward the rim reads as round
                return half4(input.color.rgb * shade, 1);
            }
            ENDHLSL
        }
    }
    Fallback Off
}
