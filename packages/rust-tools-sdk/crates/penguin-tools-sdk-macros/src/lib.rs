//! Proc macros for `penguin-tools-sdk`. Use them through that crate.

use proc_macro::TokenStream;
use quote::{format_ident, quote};
use syn::{
    parse_macro_input, Expr, ExprArray, ExprLit, FnArg, GenericArgument, ItemFn, Lit, LitStr,
    PathArguments, ReturnType, Type,
};

#[derive(Default)]
struct ToolArgs {
    name: Option<LitStr>,
    version: Option<LitStr>,
    description: Option<LitStr>,
    effect: Option<LitStr>,
    capabilities: Vec<LitStr>,
}

/// Declares a function as a `penguin:tools` tool.
///
/// The function must take exactly one typed argument and return
/// `Result<Out, ToolFailure>`. Both `In` and `Out` must implement
/// `schemars::JsonSchema`. The macro leaves the function untouched and adds
/// `<fn_name>_descriptor()`, which builds the validated `ToolDescriptor`.
///
/// Attributes: `name`, `version`, `description`, `effect`
/// (`"read" | "write" | "destructive"`) are required; `capabilities` is an
/// optional array of namespaced ids such as `"penguin:http"`.
#[proc_macro_attribute]
pub fn tool(attr: TokenStream, item: TokenStream) -> TokenStream {
    let mut args = ToolArgs::default();
    let parser = syn::meta::parser(|meta| {
        if meta.path.is_ident("name") {
            args.name = Some(meta.value()?.parse()?);
        } else if meta.path.is_ident("version") {
            args.version = Some(meta.value()?.parse()?);
        } else if meta.path.is_ident("description") {
            args.description = Some(meta.value()?.parse()?);
        } else if meta.path.is_ident("effect") {
            args.effect = Some(meta.value()?.parse()?);
        } else if meta.path.is_ident("capabilities") {
            let array: ExprArray = meta.value()?.parse()?;
            for element in array.elems {
                match element {
                    Expr::Lit(ExprLit {
                        lit: Lit::Str(s), ..
                    }) => args.capabilities.push(s),
                    other => {
                        return Err(syn::Error::new_spanned(
                            other,
                            "each capability must be a string literal",
                        ))
                    }
                }
            }
        } else {
            return Err(meta.error(
                "unsupported #[tool] attribute; expected name, version, description, effect, capabilities",
            ));
        }
        Ok(())
    });
    parse_macro_input!(attr with parser);
    let function = parse_macro_input!(item as ItemFn);

    match expand(args, function) {
        Ok(tokens) => tokens.into(),
        Err(err) => err.to_compile_error().into(),
    }
}

fn expand(args: ToolArgs, function: ItemFn) -> syn::Result<proc_macro2::TokenStream> {
    let span = function.sig.ident.span();
    let missing =
        |what: &str| syn::Error::new(span, format!("#[tool] requires `{what} = \"...\"`"));
    let name = args.name.ok_or_else(|| missing("name"))?;
    let version = args.version.ok_or_else(|| missing("version"))?;
    let description = args.description.ok_or_else(|| missing("description"))?;
    let effect_lit = args.effect.ok_or_else(|| missing("effect"))?;

    let effect = match effect_lit.value().as_str() {
        "read" => quote!(::penguin_tools_sdk::Effect::Read),
        "write" => quote!(::penguin_tools_sdk::Effect::Write),
        "destructive" => quote!(::penguin_tools_sdk::Effect::Destructive),
        _ => {
            return Err(syn::Error::new_spanned(
                effect_lit,
                "effect must be \"read\", \"write\", or \"destructive\"",
            ))
        }
    };

    let input_ty = single_input_type(&function)?;
    let output_ty = result_ok_type(&function)?;

    let vis = &function.vis;
    let descriptor_fn = format_ident!("{}_descriptor", function.sig.ident);
    let doc = format!(
        "Builds the validated descriptor for `{}`.",
        function.sig.ident
    );
    let caps = &args.capabilities;

    Ok(quote! {
        #function

        #[doc = #doc]
        #[allow(dead_code)]
        #vis fn #descriptor_fn() -> ::core::result::Result<
            ::penguin_tools_sdk::ToolDescriptor,
            ::penguin_tools_sdk::DescriptorError,
        > {
            ::penguin_tools_sdk::ToolDescriptor::new(
                #name,
                #version,
                #description,
                ::penguin_tools_sdk::schema_json::<#input_ty>()?,
                ::penguin_tools_sdk::schema_json::<#output_ty>()?,
                #effect,
                &[#(#caps),*],
            )
        }
    })
}

fn single_input_type(function: &ItemFn) -> syn::Result<Type> {
    let mut inputs = function.sig.inputs.iter();
    match (inputs.next(), inputs.next()) {
        (Some(FnArg::Typed(arg)), None) => Ok((*arg.ty).clone()),
        _ => Err(syn::Error::new_spanned(
            &function.sig.inputs,
            "a #[tool] function must take exactly one typed argument",
        )),
    }
}

fn result_ok_type(function: &ItemFn) -> syn::Result<Type> {
    let bad = |tokens: &dyn quote::ToTokens| {
        syn::Error::new_spanned(
            tokens,
            "a #[tool] function must return Result<Out, ToolFailure>",
        )
    };
    let ReturnType::Type(_, ty) = &function.sig.output else {
        return Err(bad(&function.sig));
    };
    let Type::Path(path) = ty.as_ref() else {
        return Err(bad(ty));
    };
    let Some(last) = path.path.segments.last() else {
        return Err(bad(ty));
    };
    if last.ident != "Result" {
        return Err(bad(ty));
    }
    let PathArguments::AngleBracketed(generic) = &last.arguments else {
        return Err(bad(ty));
    };
    match generic.args.first() {
        Some(GenericArgument::Type(ok)) => Ok(ok.clone()),
        _ => Err(bad(ty)),
    }
}
